"""Bounded, metadata-only request diagnostics. Never accept arbitrary payload fields."""
import json
import threading
from collections import deque
from datetime import datetime, timezone

DEFAULT_ENDPOINT = 'https://logs.conch-labs.com/ingest'

FIELDS = {'method', 'path', 'model', 'requested_model', 'upstream_model', 'stream', 'request_bytes',
          'attempt', 'status', 'phase', 'elapsed_seconds', 'wait_seconds', 'retry_at',
          'response_bytes', 'exception_type', 'reason', 'accounts', 'has_text', 'has_tool',
          'has_thinking', 'terminal', 'error', 'pending_seconds', 'account', 'from_account',
          'tokens_count', 'latency_ms', 'failed', 'switch', 'provider_reasons', 'provider_status', 'retry_delay'}


class Diagnostics:
    def __init__(self, path=None, max_bytes=5_000_000):
        self.path = path
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self.events = deque(maxlen=500)
        self.write_error = False

    def record(self, request_id, event, **fields):
        item = {'at': datetime.now(timezone.utc).isoformat(), 'request_id': request_id, 'event': event}
        item.update({key: value for key, value in fields.items() if key in FIELDS})
        with self.lock:
            self.events.append(item)
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                        self.path.replace(self.path.with_suffix('.previous.jsonl'))
                    with self.path.open('a', encoding='utf-8') as output:
                        output.write(json.dumps(item, ensure_ascii=False) + '\n')
                    self.write_error = False
                except OSError:
                    self.write_error = True
        return item

    def snapshot(self):
        with self.lock:
            return {'events': list(self.events), 'log_write_error': self.write_error,
                    'log_path': str(self.path) if self.path else None}


def export_diagnostics(controller, destination, anonymize=False):
    """Copy a bounded diagnostic bundle; never traverse auth or configuration files."""
    import platform
    import zipfile
    from pathlib import Path
    from runtime import VERSION
    destination = Path(destination)
    excluded = {controller.data_dir / name for name in ('gateway-diagnostics.jsonl', 'gateway-diagnostics.previous.jsonl', 'activity.json', 'provider-diagnostics.jsonl', 'provider-diagnostics.previous.jsonl')}
    if destination.resolve() in {p.resolve() for p in excluded}:
        raise ValueError('Choose a different destination for the exported log.')
    report = {'version': VERSION, 'exported_at': datetime.now(timezone.utc).isoformat(),
              'platform': platform.system(), 'jobs': None, 'accounts': None,
              'notes': 'Request lifecycle metadata; no prompts, responses, tokens or configuration credentials.'}
    for key, operation in [('jobs', controller.quota_wait_status), ('accounts', controller.accounts)]:
        try:
            report[key] = operation()
            if key == 'accounts':
                allowed = {'name', 'disabled', 'status', 'unavailable', 'cooldowns', 'success', 'failed', 'restriction_reason'}
                report[key] = [{k: a.get(k) for k in allowed} for a in report[key]]
        except Exception as error:
            report[key] = {'unavailable': type(error).__name__}
    aliases = {}
    def protect(data):
        if not anonymize:
            return data
        import re
        def replacement(match):
            identity = match.group(0).lower()
            if identity not in aliases:
                aliases[identity] = 'account-' + str(len(aliases) + 1)
            return aliases[identity]
        return re.sub(r'[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
                      replacement, data.decode('utf-8')).encode('utf-8')
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('snapshot.json', protect(json.dumps(report, ensure_ascii=False, indent=2).encode()))
        for path in sorted(excluded):
            if path.is_file():
                # Read bytes once: the writer may rotate while an export is in progress.
                try:
                    data = path.read_bytes()
                except FileNotFoundError:
                    continue
                archive.writestr(path.name, protect(data))
    return destination


def save_upload_token(controller, endpoint, token):
    from backend import atomic_write, dpapi
    if not token or any(character in token for character in '\r\n'):
        raise ValueError('Invalid upload access token.')
    atomic_write(controller.data_dir / 'diagnostic-upload-token.dpapi',
                 dpapi(json.dumps({'endpoint':endpoint, 'token':token}).encode()))


def read_upload_token(controller, endpoint):
    from backend import dpapi
    path = controller.data_dir / 'diagnostic-upload-token.dpapi'
    if not path.exists():
        return None
    value = json.loads(dpapi(path.read_bytes(), decrypt=True))
    return value.get('token') if value.get('endpoint') == endpoint else None


def send_diagnostics(controller, endpoint, token=None):
    """Invoked by the UI only after the owner explicitly confirms this export."""
    import tempfile
    import urllib.request
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Use an HTTPS endpoint without embedded credentials.')
    token = token or read_upload_token(controller, endpoint)
    if not token or any(character in token for character in '\r\n'):
        raise ValueError('The diagnostic upload access token is missing or invalid.')
    with tempfile.TemporaryDirectory() as directory:
        path = export_diagnostics(controller, __import__('pathlib').Path(directory) / 'diagnostics.zip', anonymize=True)
        request = urllib.request.Request(endpoint, data=path.read_bytes(), method='POST',
            headers={'Content-Type':'application/zip', 'User-Agent':'GeminiAccounts-Diagnostics',
                     'Authorization':'Bearer ' + token, 'X-Filename':'logs.zip'})
        # Do not follow redirects: approval applies to the displayed recipient only.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=60) as response:
            return response.status
