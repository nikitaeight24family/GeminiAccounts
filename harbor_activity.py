"""Non-secret, per-key TokenHarbor request history for the sidebar."""
import hashlib
import json
from datetime import datetime, timezone

from backend import atomic_write


def key_id(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]


def key_label(key):
    return key[:7] + '…' + key[-4:]


class HarborActivity:
    def __init__(self, path):
        self.path = path
        try:
            self.state = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            self.state = {'seen': [], 'keys': {}, 'latest': None}

    def observe(self, records, auth_keys):
        """Associate completed proxy usage with the actual upstream key."""
        seen = set(self.state.get('seen', []))
        changed = False
        for record in sorted(records, key=lambda item: item.get('timestamp') or ''):
            key = auth_keys.get(record.get('auth_index'))
            ident = record.get('execution_id') or record.get('request_id')
            if not key or not ident or ident in seen:
                continue
            seen.add(ident)
            self.state.setdefault('seen', []).append(ident)
            fingerprint = key_id(key)
            status = (record.get('fail') or {}).get('status_code') or 0
            event = {'at': record.get('timestamp') or datetime.now(timezone.utc).isoformat(),
                     'failed': bool(record.get('failed')), 'status': status,
                     'label': key_label(key)}
            previous = self.state.setdefault('keys', {}).get(fingerprint)
            if not previous or event['at'] >= previous.get('at', ''):
                self.state['keys'][fingerprint] = event
            latest = self.state.get('latest')
            if not latest or event['at'] >= latest.get('at', ''):
                self.state['latest'] = dict(event, key_id=fingerprint)
            changed = True
        if changed:
            self.state['seen'] = self.state['seen'][-10000:]
            atomic_write(self.path, json.dumps(self.state, ensure_ascii=False).encode('utf-8'))
        return changed

    def status(self, key):
        return self.state.get('keys', {}).get(key_id(key))
