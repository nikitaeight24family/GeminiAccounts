"""Local, bounded storage for user request text sent through the gateway."""
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_SECRET = re.compile(r"(?i)(bearer\s+|(?:sk|thk|api)[_-])[A-Za-z0-9._~+/=-]{12,}")

def _text(value):
    if isinstance(value, str): return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str): parts.append(item)
            elif isinstance(item, dict) and item.get('type') in ('text', 'input_text') and isinstance(item.get('text'), str): parts.append(item['text'])
        return '\n'.join(parts)
    return ''

def extract_user_text(request):
    messages = request.get('messages')
    if not isinstance(messages, list): return _text(request.get('input'))
    return '\n\n'.join(value for message in messages if isinstance(message, dict) and message.get('role') == 'user' for value in [_text(message.get('content'))] if value)

class RequestTextStore:
    def __init__(self, path, max_bytes=20_000_000, max_chars=20_000):
        self.path, self.max_bytes, self.max_chars = Path(path), max_bytes, max_chars
        self.lock = threading.RLock()

    def record(self, request_id, model, path, request):
        value = extract_user_text(request)
        if not value: return False
        item = {'at': datetime.now(timezone.utc).isoformat(), 'request_id': request_id, 'model': model, 'path': path, 'text': _SECRET.sub('[REDACTED]', value)[:self.max_chars]}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes: self.path.replace(self.path.with_suffix('.previous.jsonl'))
            with self.path.open('a', encoding='utf-8') as output: output.write(json.dumps(item, ensure_ascii=False) + '\n')
        return True
