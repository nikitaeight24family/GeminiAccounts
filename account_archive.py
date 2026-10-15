"""Portable, encrypted Omni account archives.

The archive deliberately contains provider auth records rather than machine
paths, DPAPI blobs, or gateway indexes.  Those records can therefore be
restored on another operating system and assigned fresh local indexes by the
gateway.
"""
import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend import AccountError, atomic_write
from chatgpt_auth import gateway_credential


FORMAT = 'omni-account-archive'
VERSION = 1
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MIN_PASSWORD_LENGTH = 8
SAFE_NAME = re.compile(r'^[A-Za-z0-9._@+%=-]{1,240}$')


def _password(value):
    value = str(value or '')
    if len(value) < MIN_PASSWORD_LENGTH:
        raise AccountError('Archive password must contain at least 8 characters.')
    return value.encode('utf-8')


def _key(password, salt):
    # scrypt is available in the supported Python runtimes and is portable
    # across Windows, macOS and Linux.  The parameters are encoded in the
    # envelope so a future archive version can change them safely.
    return hashlib.scrypt(_password(password), salt=salt, n=32768, r=8, p=1, dklen=32,
                          maxmem=128 * 1024 * 1024)


def _safe_name(value):
    name = Path(str(value or '')).name
    if name != str(value) or not SAFE_NAME.fullmatch(name):
        raise AccountError('The archive contains an invalid account filename.')
    return name


def _record(provider, name, payload, metadata=None):
    if provider not in ('antigravity', 'codex'):
        raise AccountError('This account type is not supported by portable archives yet.')
    name = _safe_name(name)
    if not isinstance(payload, dict):
        raise AccountError('The archive contains an invalid account record.')
    if provider == 'codex':
        credential = gateway_credential(payload)
        payload = credential
    elif payload.get('type') != 'antigravity' or not payload.get('email') or not payload.get('refresh_token'):
        raise AccountError('The Google account record is incomplete.')
    return {'provider': provider, 'name': name, 'payload': payload,
            'metadata': metadata if isinstance(metadata, dict) else {}}


def write_archive(path, records, password, automatic_credentials=None):
    records = [_record(item['provider'], item['name'], item['payload'], item.get('metadata'))
               for item in records if isinstance(item, dict)]
    if not records:
        raise AccountError('Select at least one account to export.')
    extras = []
    for item in automatic_credentials or []:
        if not isinstance(item, dict) or not item.get('email'):
            continue
        if not item.get('password') or not item.get('secret'):
            continue
        extras.append({'email': str(item['email']), 'password': str(item['password']),
                       'secret': str(item['secret'])})
    plaintext = json.dumps({
        'format': FORMAT, 'version': VERSION,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'accounts': records, 'automatic_credentials': extras,
    }, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = {'format': FORMAT, 'version': VERSION, 'kdf': 'scrypt',
              'n': 32768, 'r': 8, 'p': 1,
              'salt': base64.b64encode(salt).decode('ascii'),
              'nonce': base64.b64encode(nonce).decode('ascii')}
    aad = json.dumps(header, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ciphertext = AESGCM(_key(password, salt)).encrypt(nonce, plaintext, aad)
    envelope = {**header, 'ciphertext': base64.b64encode(ciphertext).decode('ascii')}
    atomic_write(Path(path), json.dumps(envelope, separators=(',', ':')).encode('utf-8'))
    return {'accounts': len(records), 'automatic_credentials': len(extras)}


def read_archive(path, password):
    path = Path(path)
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise AccountError('The archive is too large.')
        envelope = json.loads(path.read_text('utf-8'))
    except AccountError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise AccountError('The selected file is not an Omni account archive.') from None
    if not isinstance(envelope, dict) or envelope.get('format') != FORMAT or envelope.get('version') != VERSION:
        raise AccountError('This archive version is not supported.')
    try:
        salt = base64.b64decode(envelope['salt'], validate=True)
        nonce = base64.b64decode(envelope['nonce'], validate=True)
        ciphertext = base64.b64decode(envelope['ciphertext'], validate=True)
        header = {key: envelope[key] for key in ('format', 'version', 'kdf', 'n', 'r', 'p', 'salt', 'nonce')}
        aad = json.dumps(header, sort_keys=True, separators=(',', ':')).encode('utf-8')
        plaintext = AESGCM(_key(password, salt)).decrypt(nonce, ciphertext, aad)
        data = json.loads(plaintext.decode('utf-8'))
    except AccountError:
        raise
    except Exception:
        raise AccountError('The archive password is incorrect or the archive is damaged.') from None
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != VERSION:
        raise AccountError('The archive contents are invalid.')
    records = [_record(item.get('provider'), item.get('name'), item.get('payload'), item.get('metadata'))
               for item in data.get('accounts', []) if isinstance(item, dict)]
    if not records:
        raise AccountError('The archive does not contain any supported accounts.')
    credentials = []
    for item in data.get('automatic_credentials', []):
        if isinstance(item, dict) and item.get('email') and item.get('password') and item.get('secret'):
            credentials.append({'email': str(item['email']), 'password': str(item['password']),
                                'secret': str(item['secret'])})
    return {'records': records, 'automatic_credentials': credentials,
            'created_at': data.get('created_at', '')}
