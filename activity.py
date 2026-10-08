"""Persist only account/request metrics, never prompts or credential data."""
import json
import re
from datetime import datetime, timezone
from backend import atomic_write
from provider_errors import failure_reason, provider_error_metadata
from gateway_diagnostics import Diagnostics


class Activity:
    def __init__(self, path):
        self.path = path
        self.diagnostics = Diagnostics(path.with_name('provider-diagnostics.jsonl'))
        try:
            self.state = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            self.state = {'since': datetime.now(timezone.utc).isoformat(), 'events': [], 'stats': {}, 'latest': {}, 'seen': [], 'attempts': {}}
        for event in self.state['events']:
            if re.search(r'[\u0400-\u04ff]', event.get('reason', '')):
                event['reason'] = self.reason(event.get('code', 0)) if event.get('failed') else (
                    'The model account changed; the proxy did not report the exact reason' if event.get('switch') else 'Response received')

    @staticmethod
    def reason(code):
        if code == 429:
            return failure_reason(code)
        if code in (401, 403):
            return f'Google returned {code}: access denied'
        if code >= 500:
            return f'Service error {code}'
        return f'Request error {code}' if code else 'Request failed without a status code'

    def pin_model_aliases(self, aliases):
        """Keep historical model captions accurate before changing a gateway alias."""
        changed = False
        for stats in self.state['stats'].values():
            model = stats.get('last_model')
            if model in aliases:
                stats['last_model'] = aliases[model]
                changed = True
        for event in self.state['events']:
            model = event.get('upstream_model') or event.get('model')
            if model in aliases:
                event['upstream_model'] = aliases[model]
                changed = True
        for event in self.state.get('latest', {}).values():
            model = event.get('upstream_model') or event.get('model')
            if model in aliases:
                event['upstream_model'] = aliases[model]
                changed = True
        if changed:
            atomic_write(self.path, json.dumps(self.state, ensure_ascii=False).encode('utf-8'))

    def ingest(self, records, accounts):
        known = {a['auth_index']: a['name'] for a in accounts}
        issues = {a['name']: a.get('access_issue') for a in accounts}
        seen = set(self.state['seen'])
        changed = False
        for record in sorted(records, key=lambda r: r.get('timestamp', '')):
            name = known.get(record.get('auth_index'))
            identifier = record.get('execution_id') or record.get('request_id')
            if not name or not identifier or identifier in seen:
                continue
            seen.add(identifier)
            self.state['seen'].append(identifier)
            changed = True
            model = record.get('alias') or record.get('model') or 'Unknown model'
            upstream_model = record.get('upstream_model') or record.get('model') or model
            timestamp = record.get('timestamp') or datetime.now(timezone.utc).isoformat()
            failed = bool(record.get('failed'))
            code = (record.get('fail') or {}).get('status_code', 0)
            trace = record.get('trace_id') or record.get('request_id')
            tokens = (record.get('tokens') or {}).get('total_tokens', 0)
            latency = record.get('latency_ms', 0)
            stats = self.state['stats'].setdefault(name, {'success': 0, 'failed': 0, 'tokens': 0, 'latency_ms': 0, 'last': ''})
            stats['failed' if failed else 'success'] += 1
            stats['tokens'] += max(0, tokens or 0)
            stats['latency_ms'] += max(0, latency or 0)
            if timestamp >= stats.get('last', ''):
                stats['last'] = timestamp
                stats['last_model'] = upstream_model
            previous = self.state['latest'].get(model)
            attempt = self.state['attempts'].get(trace) if trace else None
            if attempt and attempt.get('model') != model:
                attempt = None
            failure = record.get('fail') or {}
            reason = (failure_reason(code, failure.get('body')) or self.reason(code)) if failed else 'Response received'
            if failed and code == 403 and issues.get(name) == 'verification':
                reason = 'Google requires account verification; this is not a quota error'
            switched = not failed and previous and timestamp >= previous['at'] and previous['name'] != name
            if attempt and attempt['name'] != name:
                switched = True
                reason = 'Retry using another account: ' + self.reason(attempt['code'])
            elif switched:
                reason = 'The model account changed; the proxy did not report the exact reason'
            event = {'id': identifier, 'at': timestamp, 'name': name, 'model': model, 'failed': failed,
                     'upstream_model': upstream_model,
                     'code': code, 'tokens': tokens, 'latency_ms': latency, 'switch': bool(switched), 'reason': reason,
                     'from': attempt['name'] if switched and attempt else previous['name'] if switched else None}
            self.state['events'].append(event)
            self.diagnostics.record(identifier, 'provider_attempt', model=model, upstream_model=upstream_model,
                account=name, from_account=event['from'], status=code, tokens_count=tokens, latency_ms=latency,
                failed=failed, switch=bool(switched), reason=reason, **provider_error_metadata(failure.get('body')))
            if failed and trace:
                self.state['attempts'][trace] = {'name': name, 'code': code, 'model': model}
            else:
                current = {'name': name, 'at': timestamp, 'model': model, 'upstream_model': upstream_model}
                if not previous or timestamp >= previous['at']:
                    self.state['latest'][model] = current
                self.state['attempts'].pop(trace, None)
        if changed:
            self.state['events'] = self.state['events'][-2000:]
            self.state['seen'] = self.state['seen'][-10000:]
            self.state['attempts'] = dict(list(self.state['attempts'].items())[-500:])
            atomic_write(self.path, json.dumps(self.state, ensure_ascii=False).encode('utf-8'))
        return self.state
