"""Local, cancellable quota waiting. No synthetic assistant output or tool calls."""
import http.client
import json
import queue
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend import Controller, dpapi, AccountError
import yaml
from model_context import context_window, strip_context_suffix
from response_guard import StreamProbe, usable_message
from gateway_diagnostics import Diagnostics
from request_texts import RequestTextStore
from provider_errors import failure_reason, provider_error_metadata
from chatgpt_routing import accounts_for_model
from model_policy import is_disabled_model

PING = b'event: ping\ndata: {"type":"ping"}\n\n'
HOP = {'connection', 'transfer-encoding', 'content-length', 'keep-alive',
       'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade', 'host'}


SDK_IDENTITY = "You are a Claude agent, built on Anthropic's Claude Agent SDK"

# The Anthropic client does not know the context size of a custom Claude
# route (for example a Claude-shaped alias backed by Gemini).  It can therefore
# send the complete transcript past the upstream limit before its own compact
# pass runs.  Keep a safety margin below the provider limit and compact only
# requests that are genuinely large; ordinary requests are byte-for-byte
# untouched.
COMPACTION_ESTIMATE_BYTES_PER_TOKEN = 6
COMPACTION_TRIGGER_RATIO = 0.90
COMPACTION_TARGET_RATIO = 0.82
COMPACTION_MARKER = '[Omni compacted older conversation to fit the upstream context window.]'


def _encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def estimate_input_tokens(request):
    """Estimate input tokens without sending an over-limit request upstream."""
    return max(1, (_encoded_size(request) + COMPACTION_ESTIMATE_BYTES_PER_TOKEN - 1) //
               COMPACTION_ESTIMATE_BYTES_PER_TOKEN)


def _append_compaction_marker(request):
    system = request.get('system')
    if isinstance(system, str):
        request['system'] = system.rstrip() + '\n\n' + COMPACTION_MARKER
        return
    if isinstance(system, list):
        blocks = list(system)
        blocks.append({'type': 'text', 'text': COMPACTION_MARKER})
        request['system'] = blocks
        return
    request['system'] = COMPACTION_MARKER


def compact_messages_request(request, model, aliases):
    """Trim the oldest transcript turns when a custom route reaches its limit.

    The current user turn and the newest assistant/tool turns are retained. A
    marker in the system prompt tells the model that older turns were removed,
    while all under-budget requests keep the original object unchanged.
    """
    upstream = aliases.get(model, model)
    limit = context_window(upstream)
    messages = request.get('messages')
    if not limit or not isinstance(messages, list) or len(messages) < 2:
        return request, None
    estimated = estimate_input_tokens(request)
    trigger = int(limit * COMPACTION_TRIGGER_RATIO)
    if estimated <= trigger:
        return request, None

    target_bytes = int(limit * COMPACTION_ESTIMATE_BYTES_PER_TOKEN * COMPACTION_TARGET_RATIO)
    kept = list(messages)
    original_count = len(kept)
    while len(kept) > 1:
        candidate = dict(request, messages=kept)
        if _encoded_size(candidate) <= target_bytes:
            break
        kept.pop(0)
    # Claude's messages API expects the transcript to begin with a user turn.
    # Dropping a leading assistant/tool turn also avoids orphaning old tool
    # calls after the cut.
    while len(kept) > 1 and isinstance(kept[0], dict) and kept[0].get('role') != 'user':
        kept.pop(0)
    compacted = dict(request, messages=kept)
    _append_compaction_marker(compacted)

    # A single enormous tool result can still exceed the budget after all
    # previous turns have been removed. Preserve its tail, which contains the
    # newest result, and keep the request valid JSON.
    while _encoded_size(compacted) > target_bytes and kept:
        last = dict(kept[-1]) if isinstance(kept[-1], dict) else {'role': 'user', 'content': kept[-1]}
        content = last.get('content')
        if isinstance(content, str) and len(content) > 4096:
            last['content'] = '[Earlier part of this result omitted by Omni.]\n' + content[-4096:]
            kept[-1] = last
        elif isinstance(content, list) and content:
            changed = False
            blocks = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get('text'), str) and len(block['text']) > 4096:
                    block = dict(block)
                    block['text'] = '[Earlier part omitted by Omni.]\n' + block['text'][-4096:]
                    changed = True
                blocks.append(block)
            if changed:
                last['content'] = blocks
                kept[-1] = last
            else:
                break
        else:
            break
        compacted['messages'] = kept
    final_estimate = estimate_input_tokens(compacted)
    return compacted, {'original_tokens': estimated, 'final_tokens': final_estimate,
                       'original_messages': original_count, 'final_messages': len(kept),
                       'limit': limit}


def augment_model_catalog(value, aliases):
    """Advertise context limits for Claude-shaped aliases in the live catalog."""
    if not isinstance(value, dict) or not isinstance(value.get('data'), list):
        return value, False
    changed = False
    rows = []
    for item in value['data']:
        if not isinstance(item, dict):
            rows.append(item)
            continue
        row = dict(item)
        upstream = aliases.get(row.get('id'), row.get('id'))
        limit = context_window(upstream)
        if limit and row.get('max_input_tokens') != limit:
            row['max_input_tokens'] = limit
            changed = True
        # Anthropic's catalog also exposes max_tokens. Keep a conservative
        # output default without overwriting an upstream value.
        if limit and 'max_tokens' not in row:
            row['max_tokens'] = 8192
            changed = True
        rows.append(row)
    if changed:
        value = dict(value, data=rows)
    return value, changed


def free_offer_ended(error):
    """Recognize a permanently retired limited-time free-model offer."""
    if isinstance(error, bytes):
        error = error.decode('utf-8', errors='replace')
    text = str(error or '').lower()
    return ('free offer' in text and ('ended' in text or 'expired' in text))


def normalize_sdk_system(request):
    """Drop only the standalone SDK identity line; never edit user messages or tools."""
    def clean(text):
        return ''.join(line for line in text.splitlines(keepends=True)
                       if line.strip() not in (SDK_IDENTITY, SDK_IDENTITY + '.'))
    system = request.get('system')
    changed = False
    if isinstance(system, str):
        value = clean(system)
        changed = value != system
        if changed:
            if value.strip():
                request['system'] = value
            else:
                request.pop('system')
    elif isinstance(system, list):
        blocks = []
        for block in system:
            if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
                value = clean(block['text'])
                if value != block['text']:
                    changed = True
                    if not value.strip():
                        continue
                    block = {**block, 'text': value}
            blocks.append(block)
        if changed:
            if blocks:
                request['system'] = blocks
            else:
                request.pop('system')
    return changed


def normalize_tool_history(request):
    """Remove orphaned Anthropic tool results before gateway conversion.

    Claude Code can resume a transcript after compaction or a reconnect with a
    ``tool_result`` whose preceding ``tool_use`` was already discarded.  The
    Gemini adapter maps those blocks to ``functionResponse`` and rejects the
    whole request when no matching ``functionCall`` exists.  Keep valid tool
    exchanges untouched and remove only results that cannot be paired with the
    immediately preceding assistant tool call.
    """
    messages = request.get('messages')
    if not isinstance(messages, list):
        return False

    cleaned = []
    pending = set()
    changed = False
    for message in messages:
        if not isinstance(message, dict):
            cleaned.append(message)
            pending.clear()
            continue
        role = message.get('role')
        content = message.get('content')
        if role == 'assistant':
            pending = {
                str(block.get('id')).strip()
                for block in content or []
                if isinstance(content, list) and isinstance(block, dict)
                and block.get('type') == 'tool_use' and block.get('id')
            }
            cleaned.append(message)
            continue
        if role != 'user' or not isinstance(content, list):
            cleaned.append(message)
            pending.clear()
            continue

        blocks = []
        message_changed = False
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                tool_id = str(block.get('tool_use_id') or '').strip()
                if not tool_id or tool_id not in pending:
                    # This is precisely the block that becomes an invalid
                    # Gemini functionResponse.  Do not send it upstream.
                    message_changed = True
                    continue
                pending.discard(tool_id)
            blocks.append(block)
        if message_changed:
            changed = True
            if blocks:
                cleaned.append({**message, 'content': blocks})
            # An all-tool-result message is omitted instead of forwarding an
            # empty Anthropic message, which some clients reject themselves.
        else:
            cleaned.append(message)
        pending.clear()

    if not changed:
        return False
    if not cleaned:
        # Keep the Anthropic request structurally valid when the transcript
        # consisted solely of orphaned tool results.
        cleaned = [{'role': 'user', 'content': '[Omni repaired an orphaned tool result.]'}]
    request['messages'] = cleaned
    return True


def deadline(item):
    try:
        return datetime.fromisoformat(item['retry_at'].replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0


def google_routed_model(model):
    return not model.startswith('gpt-') and 'tokenharbor' not in model


def quota_wait(files, model, aliases, now=None):
    """Wait only for actual quota blocks, scoped to the requested upstream model."""
    now = time.time() if now is None else now
    model = strip_context_suffix(model)
    model = aliases.get(model, model)
    # Scope each wait to the requested provider; never mix Google and GPT pools.
    if 'tokenharbor' in model or model.startswith('api-'):
        return None
    providers = ('xai',) if model.startswith('grok-') else ('codex',) if model.startswith('gpt-') else ('antigravity', 'claude', 'anthropic') if model.startswith('claude-') else ('antigravity',)
    quota = []
    enabled = [a for a in files if not a.get('disabled') and
               a.get('provider', a.get('type')) in providers]
    # A model present in the free subscription catalog must never be held up
    # or counted against paid GPT credentials.  The catalog is dynamic and is
    # refreshed from /auth-files/models, so this also covers future models.
    if model.startswith('gpt-'):
        enabled = accounts_for_model(enabled, model)
    for account in enabled:
        if account.get('access_issue') in ('verification', 'login', 'denied'):
            continue
        blocks = [b for b in account.get('cooldowns', []) if deadline(b) > now and
                  (b.get('scope') == 'credential' or b.get('model_key') == model)]
        if not blocks:
            # Verification is not a reason to hold a request forever.
            try:
                code = json.loads(account.get('status_message') or '{}').get('error', {}).get('code')
            except (ValueError, TypeError, AttributeError):
                code = None
            if code in (401, 403):
                continue
            return None
        quota_blocks = [b for b in blocks if b.get('http_status') == 429 and b.get('reason') == 'quota']
        if quota_blocks:
            quota.append(max(deadline(b) for b in blocks))
    return min(quota) if quota else None


class QueueServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, upstream, key, client_keys, aliases):
        super().__init__(address, Handler)
        self.upstream = upstream
        self.key = key
        self.client_keys = client_keys
        self.aliases = aliases
        self.jobs = {}
        self.updating = False
        self.quota_guard = None
        self.diagnostics = Diagnostics()
        self.request_texts = None
        self.lock = threading.Lock()
        self.poll_seconds = 3
        self.retry_base_seconds = 5
        self.retry_max_seconds = 60
        self.heartbeat_seconds = 10
        self.verifications_path = None
        self.aliases_checked = 0
        self.model_catalog = {}
        self.model_catalog_checked = 0
        self.retired_models = set()
        self.retired_fallbacks = {}

    def retire_model(self, model):
        model = str(model or '').strip()
        if model:
            with self.lock:
                self.retired_models.add(model)

    def model_retired(self, model):
        with self.lock:
            return model in self.retired_models

    def replacement_for_retired(self, model):
        """Pick a live Claude-shaped route for an ended offer.

        Claude Code can keep the old model in an already-open session even
        after the gateway catalog has been refreshed.  Keep that request
        usable while the client reloads its menu by selecting the closest
        currently advertised route (Haiku first, then another Claude route).
        """
        with self.lock:
            if model in self.retired_fallbacks:
                return self.retired_fallbacks[model]
            retired = set(self.retired_models)
            aliases = set(self.aliases)
        candidates = sorted(
            candidate for candidate in aliases
            if candidate != model and candidate not in retired
            and candidate.startswith('claude-')
            and 'tokenharbor' not in candidate.lower()
        )
        if not candidates:
            return None
        lowered = str(model).lower()
        family = 'haiku' if 'haiku' in lowered else 'sonnet' if 'sonnet' in lowered else 'opus' if 'opus' in lowered else ''
        family_candidates = [candidate for candidate in candidates if family and family in candidate.lower()]
        pool = family_candidates or candidates
        # Prefer a normal Flash route when several same-family routes exist.
        pool.sort(key=lambda candidate: (0 if 'flash' in candidate.lower() else 1, candidate))
        fallback = pool[0]
        with self.lock:
            self.retired_fallbacks[model] = fallback
        return fallback

    def filter_retired_models(self, value):
        """Remove aliases retired by an upstream availability response."""
        if not isinstance(value, dict) or not isinstance(value.get('data'), list):
            return value, False
        with self.lock:
            retired = set(self.retired_models)
        if not retired:
            return value, False
        rows = [item for item in value['data']
                if not isinstance(item, dict) or item.get('id') not in retired]
        if len(rows) == len(value['data']):
            return value, False
        return dict(value, data=rows), True

    def refresh_model_catalog(self, accounts):
        """Refresh per-account GPT catalogs without naming a specific model."""
        if time.monotonic() - self.model_catalog_checked < 15:
            for account in accounts:
                if account.get('name') in self.model_catalog:
                    account['supported_models'] = self.model_catalog[account['name']]
            return
        self.model_catalog_checked = time.monotonic()
        conn = http.client.HTTPConnection(*self.upstream, timeout=5)
        try:
            for account in accounts:
                plan = str(account.get('plan_type') or (account.get('id_token') or {}).get('plan_type') or (account.get('quota') or {}).get('plan_type') or '').strip().lower()
                if account.get('provider', account.get('type')) != 'codex' or not plan.startswith('free'):
                    continue
                query = '/v0/management/auth-files/models?' + urllib.parse.urlencode({'name': account.get('name', '')})
                conn.request('GET', query, headers={'Authorization': 'Bearer ' + self.key})
                response = conn.getresponse()
                if response.status != 200:
                    response.read()
                    continue
                payload = json.loads(response.read() or b'{}')
                models = frozenset(item.get('id') for item in payload.get('models', [])
                                   if isinstance(item, dict) and isinstance(item.get('id'), str)
                                   and item['id'].startswith('gpt-'))
                self.model_catalog[account.get('name')] = models
                account['supported_models'] = models
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            pass
        finally:
            conn.close()

    def refresh_aliases(self):
        # Hot model selection must also update quota-wait model scoping.
        with self.lock:
            if time.monotonic() - self.aliases_checked < 1:
                return
            self.aliases_checked = time.monotonic()
        conn = http.client.HTTPConnection(*self.upstream, timeout=3)
        try:
            conn.request('GET', '/v0/management/oauth-model-alias', headers={'Authorization': 'Bearer ' + self.key})
            response = conn.getresponse()
            if response.status == 200:
                result = json.loads(response.read())
                if 'oauth-model-alias' in result:
                    aliases = (result['oauth-model-alias'] or {}).get('antigravity', [])
                    with self.lock:
                        self.aliases = {item['alias']: item['name'] for item in aliases}
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            pass
        finally:
            conn.close()

    def accounts(self):
        conn = http.client.HTTPConnection(*self.upstream, timeout=12)
        try:
            conn.request('GET', '/v0/management/auth-files', headers={'Authorization': 'Bearer ' + self.key})
            response = conn.getresponse()
            if response.status != 200:
                raise OSError('Account metadata unavailable')
            files = json.loads(response.read()).get('files', [])
            if self.verifications_path:
                try:
                    issues = json.loads(dpapi(self.verifications_path.read_bytes(), decrypt=True))
                    for account in files:
                        account.update(issues.get(account.get('name'), {}))
                except (OSError, ValueError):
                    pass
            return files
        finally:
            conn.close()

    def snapshot(self):
        with self.lock:
            return {'jobs': [dict(j, upstream_model=self.aliases.get(j['model'], j['model'])) for j in self.jobs.values()], 'poll_seconds': self.poll_seconds, 'diagnostics_enabled': True, 'log_write_error': self.diagnostics.write_error}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Never log credentials, request bodies, or Google verification links.

    def trace(self, event, **fields):
        elapsed = round(time.monotonic() - self.trace_started, 3)
        fields['elapsed_seconds'] = elapsed
        fields.setdefault('response_bytes', self.response_bytes)
        self.server.diagnostics.record(self.request_id, event, **fields)
        with self.server.lock:
            job = self.server.jobs.get(self.request_id)
            if job is not None:
                job.update(phase=event, elapsed_seconds=elapsed, last_event_at=time.time())

    def chunk(self, data):
        self.wfile.write(('%x\r\n' % len(data)).encode() + data + b'\r\n')
        self.wfile.flush()

    def await_upstream(self, operation, stream, cleanup=None):
        """Keep the client alive while upstream headers or the next bytes are pending."""
        pending_since = time.monotonic()
        results = queue.Queue()
        cancelled = threading.Event()
        def run():
            try:
                value = operation()
                results.put((value, None))
                if cancelled.is_set() and cleanup:
                    cleanup(value)
            except Exception as error:
                results.put((None, error))
        threading.Thread(target=run, daemon=True).start()
        try:
            while True:
                try:
                    value, error = results.get(timeout=self.server.heartbeat_seconds)
                    if error:
                        raise error
                    return value
                except queue.Empty:
                    self.trace('upstream_pending', pending_seconds=round(time.monotonic() - pending_since, 3))
                    if stream and self.response_started:
                        self.chunk(self.keepalive)
        except Exception:
            cancelled.set()
            if cleanup:
                try:
                    value, error = results.get_nowait()
                    if error is None:
                        cleanup(value)
                except queue.Empty:
                    pass
            raise

    def start_stream(self, stream):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.response_started = True

    def json_reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        self.response_started = False
        self.request_id = secrets.token_hex(8)
        self.trace_started = time.monotonic()
        self.response_bytes = 0
        self.keepalive = PING if self.path.split('?')[0] == '/v1/messages' else b': keep-alive\n\n'
        tokens = [self.headers.get('x-api-key', ''), self.headers.get('Authorization', '').removeprefix('Bearer ')]
        if self.path in ('/v0/management/quota-wait', '/v0/management/diagnostics', '/v0/management/update-lock'):
            if not any(secrets.compare_digest(token.encode(), self.server.key.encode()) for token in tokens):
                self.json_reply(401, {'error': {'type': 'authentication_error', 'message': 'Unauthorized'}})
                return
            if self.path.endswith('update-lock'):
                if self.command not in ('POST', 'DELETE'):
                    self.json_reply(405, {'error':'Use POST or DELETE'})
                    return
                if self.command == 'DELETE':
                    with self.server.lock:
                        self.server.updating = False
                    self.json_reply(200, {'locked':False})
                    return
                with self.server.lock:
                    if self.server.jobs:
                        self.json_reply(409, {'error':'Requests are running'})
                        return
                    self.server.updating = True
                self.json_reply(200, {'locked':True})
                return
            self.json_reply(200, self.server.snapshot() if self.path.endswith('quota-wait') else dict(self.server.diagnostics.snapshot(), **self.server.snapshot()))
            return
        self.trace('received', method=self.command, path=self.path.split('?')[0])
        size = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(size) if size else None
        inference = self.command == 'POST' and self.path.split('?')[0] in ('/v1/messages', '/v1/responses', '/v1/chat/completions')
        if not inference:
            if self.command == 'POST' and self.path.split('?')[0] == '/v1/messages/count_tokens':
                try:
                    request = json.loads(body)
                    if normalize_sdk_system(request):
                        self.trace('sdk_identity_removed')
                        body = json.dumps(request, ensure_ascii=False).encode()
                    raw_model = request.get('model')
                    normalized = strip_context_suffix(raw_model)
                    if isinstance(normalized, str):
                        self.trace('token_count_requested', model=normalized, requested_model=raw_model)
                        request['model'] = normalized
                        body = json.dumps(request, ensure_ascii=False).encode()
                        upstream = self.server.aliases.get(normalized, normalized)
                        limit = context_window(upstream)
                        estimated = estimate_input_tokens(request)
                        if limit and estimated > int(limit * COMPACTION_TRIGGER_RATIO):
                            # Claude Code uses count_tokens to decide whether to
                            # compact. Do not forward an already-over-limit
                            # count request to a provider that rejects it first.
                            self.trace('token_count_compaction_hint', model=normalized,
                                       upstream_model=upstream, estimated_tokens=estimated,
                                       limit=limit)
                            self.json_reply(200, {'input_tokens': estimated})
                            return
                except (ValueError, TypeError, AttributeError):
                    pass
            if self.path.split('?')[0] == '/v1/models':
                self.forward_model_catalog(body)
            else:
                self.forward(body)
            return
        if not any(secrets.compare_digest(token.encode(), key.encode()) for token in tokens for key in self.server.client_keys):
            self.trace('authentication_rejected', status=401)
            self.json_reply(401, {'error': {'type': 'authentication_error', 'message': 'Invalid API key'}})
            return
        try:
            request = json.loads(body)
            model = request['model']
            if not isinstance(model, str):
                raise ValueError()
            if self.path.split('?')[0] == '/v1/messages' and normalize_sdk_system(request):
                self.trace('sdk_identity_removed')
                body = json.dumps(request, ensure_ascii=False).encode()
            if self.path.split('?')[0] == '/v1/messages' and normalize_tool_history(request):
                self.trace('tool_history_normalized')
                body = json.dumps(request, ensure_ascii=False).encode()
            requested_model = model
            request_texts = getattr(self.server, 'request_texts', None)
            if request_texts:
                request_texts.record(self.request_id, model, self.path.split('?')[0], request)
            normalized = strip_context_suffix(model)
            if normalized != model:
                model = normalized
                request['model'] = model
                body = json.dumps(request, ensure_ascii=False).encode()
            if is_disabled_model(model):
                self.trace('model_disabled', model=model, requested_model=requested_model)
                self.json_reply(404, {'error': {'type': 'invalid_request_error',
                    'code': 'model_disabled',
                    'message': 'This internal Codex review model is disabled in Omni.'}})
                return
            if self.server.model_retired(model):
                fallback = self.server.replacement_for_retired(model)
                if fallback:
                    self.trace('model_retired_fallback', model=model, fallback=fallback,
                               requested_model=requested_model)
                    model = fallback
                    request['model'] = fallback
                    body = json.dumps(request, ensure_ascii=False).encode()
                else:
                    self.trace('model_retired', model=model, requested_model=requested_model)
                    self.json_reply(410, {'error': {'type': 'invalid_request_error',
                        'code': 'model_unavailable',
                        'message': 'This model route is no longer available from its upstream provider. Refresh the model catalog and choose an available model.'}})
                    return
            if self.path.split('?')[0] == '/v1/messages':
                compacted, details = compact_messages_request(request, model, self.server.aliases)
                if details:
                    request = compacted
                    body = json.dumps(request, ensure_ascii=False).encode()
                    self.trace('context_compacted', model=model,
                               upstream_model=self.server.aliases.get(model, model), **details)
                # Compaction can discard the assistant tool call while keeping
                # its newest result.  Run the pairing check again after the
                # slice so the adapter never receives an orphaned response.
                if normalize_tool_history(request):
                    body = json.dumps(request, ensure_ascii=False).encode()
                    self.trace('tool_history_normalized_after_compaction')
        except (ValueError, KeyError, TypeError):
            self.forward(body)
            return
        stream = bool(request.get('stream'))
        guarded = self.path.split('?')[0] in ('/v1/messages', '/v1/responses', '/v1/chat/completions')
        ident = self.request_id
        attempt = 0
        self.trace('validated', model=model, requested_model=requested_model, stream=stream, request_bytes=size)
        started = False
        empty_retries = 0
        rate_retries = 0
        provider_retry_at = 0
        with self.server.lock:
            if self.server.updating:
                self.json_reply(503, {'error': {'type':'api_error', 'message':'Gateway updating. Retry shortly.'}})
                return
            self.server.jobs[ident] = {'model': model, 'state': 'running', 'since': time.time(), 'retry_at': None}
        try:
            while True:
                accounts = []
                try:
                    self.server.refresh_aliases()
                    accounts = self.server.accounts()
                    self.server.refresh_model_catalog(accounts)
                    reset = quota_wait(accounts, model, self.server.aliases)
                except (OSError, ValueError, http.client.HTTPException):
                    reset = None
                if provider_retry_at > time.time():
                    reset = max(reset or 0, provider_retry_at)
                if reset:
                    if self.server.quota_guard:
                        try:
                            if self.server.quota_guard.recover_waiting(self.server.aliases.get(model, model)):
                                continue
                        except (AccountError, OSError, ValueError):
                            pass
                    with self.server.lock:
                        was_waiting = self.server.jobs[ident].get('state') == 'waiting'
                        self.server.jobs[ident].update(state='waiting', retry_at=reset)
                    if not was_waiting:
                        self.trace('waiting_provider', retry_at=reset, wait_seconds=round(max(0, reset-time.time()), 3),
                            accounts=[{'name': a.get('name'), 'disabled': bool(a.get('disabled')), 'unavailable': bool(a.get('unavailable')),
                                       'cooldowns': [{k: c.get(k) for k in ('scope', 'model_key', 'reason', 'http_status', 'retry_at')} for c in a.get('cooldowns') or []]} for a in accounts])
                    if not started:
                        self.start_stream(stream)
                        started = True
                    self.chunk(self.keepalive if stream else b'\n')
                    # A disconnected client cancels on the next heartbeat. New accounts
                    # and manually cleared cooldowns are observed on every poll.
                    time.sleep(min(self.server.poll_seconds, max(.05, reset - time.time())))
                    continue
                with self.server.lock:
                    self.server.jobs[ident].update(state='running', retry_at=None)
                if self.server.quota_guard:
                    try:
                        self.server.quota_guard(self.server.aliases.get(model, model))
                    except (AccountError, OSError, ValueError):
                        if not started:
                            self.json_reply(503, {'error': {'type': 'api_error', 'message': 'Quota reserve check unavailable. Retry shortly.'}})
                        else:
                            self.chunk(b'event: error\ndata: {"error":{"type":"api_error","message":"Quota reserve check unavailable"}}\n\n')
                            self.wfile.write(b'0\r\n\r\n')
                        return
                attempt += 1
                self.trace('upstream_started', attempt=attempt, model=model, upstream_model=self.server.aliases.get(model, model))
                try:
                    conn, response = self.await_upstream(lambda: self.open_upstream(body), stream,
                                                         cleanup=lambda result: result[0].close())
                except (OSError, http.client.HTTPException) as upstream_exc:
                    routed_model = self.server.aliases.get(model, model)
                    if routed_model.startswith('gpt-') and not started and attempt < getattr(self.server, 'max_gpt_retries', 10):
                        self.trace('upstream_open_failed_retry', attempt=attempt, error=str(upstream_exc))
                        delay = getattr(self.server, 'retry_delay', min(0.3 * attempt, 1.5))
                        if delay > 0:
                            time.sleep(delay)
                        continue
                    raise
                started = self.response_started
                routed_model = self.server.aliases.get(model, model)
                trace_id = response.getheader('X-Cpa-Trace-Id') or ''
                parts = trace_id.split('-')
                if len(parts) >= 2 and parts[1]:
                    with self.server.lock:
                        if ident in self.server.jobs:
                            self.server.jobs[ident]['auth_index'] = parts[1]
                self.trace('upstream_headers', attempt=attempt, status=response.status)
                try:
                    if response.status in (429, 403, 502, 503, 504) or ('tokenharbor' in routed_model and response.status >= 400):
                        error = response.read()
                        self.trace('provider_rejected', status=response.status, reason=failure_reason(response.status, error) or 'Provider rejected request', **provider_error_metadata(error))
                        if 'tokenharbor' in routed_model:
                            if free_offer_ended(error):
                                self.server.retire_model(model)
                                self.server.retire_model(routed_model)
                                fallback = self.server.replacement_for_retired(model)
                                if fallback and not started:
                                    model = fallback
                                    request['model'] = fallback
                                    body = json.dumps(request, ensure_ascii=False).encode()
                                    self.trace('model_retired_from_upstream', model=routed_model,
                                               fallback=fallback, reason='free_offer_ended')
                                    continue
                                self.trace('model_retired_from_upstream', model=routed_model,
                                           reason='free_offer_ended')
                            self.deliver(response, error, started, stream)
                            return
                        # For Codex (/v1/responses): swallow all provider transient/capacity/quota errors (429, 403, 502, 503, 504).
                        # Never expose "Selected model is at capacity" to Codex.
                        # Seamlessly retry across the account pool while Codex stays in thinking state.
                        is_codex = self.path.split('?')[0] in ('/v1/responses', '/v1/chat/completions')
                        if is_codex and routed_model.startswith('gpt-') and not started:
                            max_retries = getattr(self.server, 'max_gpt_retries', 25)
                            if attempt < max_retries:
                                rate_retries += 1
                                delay = getattr(self.server, 'retry_delay', None)
                                if delay is None:
                                    delay = min(getattr(self.server, 'retry_max_seconds', 8),
                                                getattr(self.server, 'retry_base_seconds', 0.5) * (1.2 ** min(rate_retries - 1, 5)))
                                self.trace('gpt_swallowed_error_retry', attempt=attempt, status=response.status, retry_in=round(delay, 2))
                                if delay > 0:
                                    time.sleep(delay)
                                continue
                            self.deliver(response, error, started, stream)
                            return
                        try:
                            reset = quota_wait(self.server.accounts(), model, self.server.aliases)
                        except (OSError, ValueError, http.client.HTTPException):
                            reset = None
                        if routed_model.startswith('gpt-') and not reset:
                            # An unqualified GPT 429 is not proof of a quota wait.
                            self.deliver(response, error, started, stream)
                            return
                        if response.status == 429:
                            rate_retries += 1
                            delay = min(self.server.retry_max_seconds,
                                        self.server.retry_base_seconds * (2 ** min(rate_retries - 1, 8)))
                            try:
                                reported = float(response.getheader('Retry-After') or 0)
                                if reported > 0:
                                    delay = max(delay, min(reported, 3600))
                            except (ValueError, TypeError):
                                pass
                            # Account cooldowns are re-evaluated on every poll. Never
                            # copy their deadline into a sticky request-level timer:
                            # a new available account must wake this request immediately.
                            provider_retry_at = 0 if reset else time.time() + delay
                            self.trace('rate_limit_retry_scheduled', attempt=attempt,
                                retry_at=reset or provider_retry_at, wait_seconds=max(0, (reset or provider_retry_at)-time.time()))
                            continue
                        if reset:
                            continue
                        self.deliver(response, error, started, stream)
                        return
                    if guarded and response.status == 200:
                        try:
                            valid = self.deliver_validated(response, stream)
                        except ValueError:
                            self.recovery_error(stream)
                            return
                        if not valid:
                            self.trace('empty_or_failed_response', attempt=attempt)
                            empty_retries += 1
                            max_retries = 6 if routed_model.startswith('gpt-') else 2
                            if empty_retries <= max_retries:
                                with self.server.lock:
                                    self.server.jobs[ident].update(recovery_reason='empty_response', attempt=empty_retries + 1)
                                time.sleep(0.5)
                                continue
                            self.recovery_error(stream)
                        return
                    self.deliver(response, None, started, stream)
                    return
                finally:
                    conn.close()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError) as error:
            self.trace('connection_ended', exception_type=type(error).__name__)
            self.close_connection = True
        except (OSError, http.client.HTTPException) as exception:
            self.trace('upstream_error', exception_type=type(exception).__name__)
            error = {'type': 'error', 'error': {'type': 'api_error', 'message': 'Local inference service unavailable'}}
            try:
                if self.response_started:
                    self.chunk((b'event: error\ndata: ' + json.dumps(error).encode() + b'\n\n') if stream else json.dumps(error).encode())
                    self.wfile.write(b'0\r\n\r\n')
                else:
                    self.json_reply(502, error)
            except OSError:
                pass
        finally:
            self.trace('finished', attempt=attempt)
            with self.server.lock:
                self.server.jobs.pop(ident, None)

    def open_upstream(self, body):
        conn = http.client.HTTPConnection(*self.server.upstream, timeout=600)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            return conn, conn.getresponse()
        except Exception:
            conn.close()
            raise

    def deliver_validated(self, response, stream):
        """Retry only before any assistant content or tool call reaches the client."""
        if not stream:
            data = self.await_upstream(response.read, False)
            self.response_bytes += len(data)
            self.trace('nonstream_body_received')
            try:
                value = json.loads(data)
                valid = usable_message(value)
            except (ValueError, AttributeError, TypeError):
                valid = False
            if valid:
                self.deliver(response, data, self.response_started, False)
            return valid
        probe = StreamProbe()
        while True:
            data = self.await_upstream(lambda: response.read1(65536), True)
            if not data:
                break
            self.response_bytes += len(data)
            if not probe.buffer:
                self.trace('first_upstream_bytes')
            self.trace('stream_progress')
            probe.feed(data)
            if probe.usable:
                self.trace('content_available', terminal=probe.terminal, error=probe.error)
                if not self.response_started:
                    self.start_stream(True)
                self.chunk(bytes(probe.buffer))
                # Continue the original stream; never retry a tool already exposed.
                self.deliver(response, None, True, True)
                return True
            if probe.error or probe.terminal:
                self.trace('stream_terminal_without_usable_content', terminal=probe.terminal, error=probe.error)
                break
        self.trace('stream_without_answer', terminal=probe.terminal)
        return False

    def recovery_error(self, stream):
        self.trace('recovery_exhausted', status=502)
        if self.path.split('?')[0] == '/v1/responses':
            error = {'error': {'type': 'server_error', 'code': 'server_error', 'message': 'The model is currently busy. Please retry shortly.'}}
            if not self.response_started:
                self.json_reply(502, error)
            else:
                self.chunk(b'event: response.failed\ndata: ' + json.dumps(error).encode() + b'\n\n')
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            return
        error = {'type': 'error', 'error': {'type': 'api_error',
            'message': 'The model returned no usable answer after 3 attempts. Retry the request; no tool call was delivered.'}}
        if not self.response_started:
            self.json_reply(502, error)
        else:
            self.chunk((b'event: error\ndata: ' + json.dumps(error).encode() + b'\n\n') if stream else json.dumps(error).encode())
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()

    def deliver(self, response, body, started=False, stream=False):
        if not started:
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP:
                    # The client cannot observe account changes during a long backoff.
                    # Known quota waits stay inside the queue; forwarded 429s recheck shortly.
                    if response.status == 429 and key.lower() == 'retry-after':
                        value = '3'
                    self.send_header(key, value)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            self.response_started = True
        elif response.status >= 400:
            data = body if body is not None else response.read()
            if stream:
                self.chunk(b'event: error\ndata: ' + data.replace(b'\n', b' ') + b'\n\n')
            else:
                self.chunk(data)
            self.wfile.write(b'0\r\n\r\n')
            return
        if body is not None:
            if body:
                self.chunk(body)
        else:
            while True:
                data = self.await_upstream(lambda: response.read1(65536), stream)
                if not data:
                    break
                self.response_bytes += len(data)
                self.trace('stream_progress')
                self.chunk(data)
        self.wfile.write(b'0\r\n\r\n')
        self.wfile.flush()

    def forward(self, body):
        conn = None
        try:
            conn, response = self.open_upstream(body)
            self.trace('forwarded_headers', status=response.status)
            self.deliver(response, None)
            self.trace('finished')
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            if conn:
                conn.close()

    def forward_model_catalog(self, body):
        """Forward /v1/models while filling metadata for custom Claude routes."""
        conn = None
        try:
            conn, response = self.open_upstream(body)
            data = self.await_upstream(response.read, False)
            if response.status == 200:
                try:
                    value = json.loads(data)
                    value, retired = self.server.filter_retired_models(value)
                    if retired:
                        self.trace('retired_models_filtered')
                    value, changed = augment_model_catalog(value, self.server.aliases)
                except (ValueError, TypeError):
                    changed = False
                if changed:
                    data = json.dumps(value, ensure_ascii=False).encode()
                    self.trace('model_catalog_context_advertised')
            self.deliver(response, data, self.response_started, False)
            self.trace('finished')
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            if conn:
                conn.close()

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_OPTIONS = handle_request


def main():
    controller = Controller()
    config = yaml.safe_load((controller.proxy_dir / 'config.yaml').read_text('utf-8-sig'))
    key = dpapi((controller.data_dir / 'management-key.dpapi').read_bytes(), decrypt=True).decode()
    aliases = {a['alias']: a['name'] for a in config.get('oauth', {}).get('model-alias', {}).get('antigravity', [])}
    keys = config.get('access', {}).get('api-keys', [])
    server = QueueServer(('127.0.0.1', 8317), ('127.0.0.1', config['server']['port']), key, keys, aliases)
    from quota_guard import QuotaGuard
    controller.key = key
    controller.base = 'http://127.0.0.1:' + str(config['server']['port'])
    server.quota_guard = QuotaGuard(controller)
    server.diagnostics = Diagnostics(controller.data_dir / 'gateway-diagnostics.jsonl')
    server.request_texts = RequestTextStore(controller.data_dir / 'request-texts.jsonl')
    server.diagnostics.record('service', 'started', phase='ready')
    server.verifications_path = controller.verification_path
    server.serve_forever()


if __name__ == '__main__':
    main()
