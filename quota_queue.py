"""Local, cancellable quota waiting. No synthetic assistant output or tool calls."""
import http.client
import json
import queue
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend import Controller, dpapi
import yaml
from model_context import strip_context_suffix
from response_guard import StreamProbe, usable_message
from gateway_diagnostics import Diagnostics
from provider_errors import failure_reason, provider_error_metadata

PING = b'event: ping\ndata: {"type":"ping"}\n\n'
HOP = {'connection', 'transfer-encoding', 'content-length', 'keep-alive',
       'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade', 'host'}


SDK_IDENTITY = "You are a Claude agent, built on Anthropic's Claude Agent SDK"


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


def deadline(item):
    try:
        return datetime.fromisoformat(item['retry_at'].replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0


def quota_wait(files, model, aliases, now=None):
    """Wait only for actual quota blocks, scoped to the requested upstream model."""
    now = time.time() if now is None else now
    model = strip_context_suffix(model)
    model = aliases.get(model, model)
    quota = []
    enabled = [a for a in files if not a.get('disabled') and
               a.get('provider', a.get('type')) == 'antigravity']
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
        self.diagnostics = Diagnostics()
        self.lock = threading.Lock()
        self.poll_seconds = 3
        self.retry_base_seconds = 5
        self.retry_max_seconds = 60
        self.heartbeat_seconds = 10
        self.verifications_path = None
        self.aliases_checked = 0

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
                    if stream:
                        if not self.response_started:
                            self.start_stream(True)
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
                except (ValueError, TypeError, AttributeError):
                    pass
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
            requested_model = model
            normalized = strip_context_suffix(model)
            if normalized != model:
                model = normalized
                request['model'] = model
                body = json.dumps(request, ensure_ascii=False).encode()
        except (ValueError, KeyError, TypeError):
            self.forward(body)
            return
        stream = bool(request.get('stream'))
        guarded = self.path.split('?')[0] == '/v1/messages'
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
                    reset = quota_wait(accounts, model, self.server.aliases)
                except (OSError, ValueError, http.client.HTTPException):
                    reset = None
                if provider_retry_at > time.time():
                    reset = max(reset or 0, provider_retry_at)
                if reset:
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
                attempt += 1
                self.trace('upstream_started', attempt=attempt, model=model, upstream_model=self.server.aliases.get(model, model))
                conn, response = self.await_upstream(lambda: self.open_upstream(body), stream,
                                                     cleanup=lambda result: result[0].close())
                started = self.response_started
                self.trace('upstream_headers', attempt=attempt, status=response.status)
                try:
                    if response.status in (429, 403, 503):
                        error = response.read()
                        self.trace('provider_rejected', status=response.status, reason=failure_reason(response.status, error) or 'Provider rejected request', **provider_error_metadata(error))
                        try:
                            reset = quota_wait(self.server.accounts(), model, self.server.aliases)
                        except (OSError, ValueError, http.client.HTTPException):
                            reset = None
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
                            provider_retry_at = reset if reset else time.time() + delay
                            self.trace('rate_limit_retry_scheduled', attempt=attempt,
                                retry_at=provider_retry_at, wait_seconds=max(0, provider_retry_at-time.time()))
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
                            self.trace('empty_response', attempt=attempt)
                            empty_retries += 1
                            if empty_retries <= 2:
                                with self.server.lock:
                                    self.server.jobs[ident].update(recovery_reason='empty_response', attempt=empty_retries + 1)
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
            if probe.usable or probe.error:
                self.trace('content_available', terminal=probe.terminal, error=probe.error)
                if not self.response_started:
                    self.start_stream(True)
                self.chunk(bytes(probe.buffer))
                # Continue the original stream; never retry a tool already exposed.
                self.deliver(response, None, True, True)
                return True
            if probe.terminal:
                break
        self.trace('stream_without_answer', terminal=probe.terminal)
        return False

    def recovery_error(self, stream):
        self.trace('recovery_exhausted', status=502)
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

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_OPTIONS = handle_request


def main():
    controller = Controller()
    config = yaml.safe_load((controller.proxy_dir / 'config.yaml').read_text('utf-8-sig'))
    key = dpapi((controller.data_dir / 'management-key.dpapi').read_bytes(), decrypt=True).decode()
    aliases = {a['alias']: a['name'] for a in config.get('oauth', {}).get('model-alias', {}).get('antigravity', [])}
    keys = config.get('access', {}).get('api-keys', [])
    server = QueueServer(('127.0.0.1', 8317), ('127.0.0.1', config['server']['port']), key, keys, aliases)
    server.diagnostics = Diagnostics(controller.data_dir / 'gateway-diagnostics.jsonl')
    server.diagnostics.record('service', 'started', phase='ready')
    server.verifications_path = controller.verification_path
    server.serve_forever()


if __name__ == '__main__':
    main()
