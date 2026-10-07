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

PING = b'event: ping\ndata: {"type":"ping"}\n\n'
HOP = {'connection', 'transfer-encoding', 'content-length', 'keep-alive',
       'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade', 'host'}


def deadline(item):
    try:
        return datetime.fromisoformat(item['retry_at'].replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0


def quota_wait(files, model, aliases, now=None):
    """Wait only for actual quota blocks, scoped to the requested upstream model."""
    now = time.time() if now is None else now
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
        self.lock = threading.Lock()
        self.poll_seconds = 3
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
            return {'jobs': [dict(j, upstream_model=self.aliases.get(j['model'], j['model'])) for j in self.jobs.values()], 'poll_seconds': self.poll_seconds}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Never log credentials, request bodies, or Google verification links.

    def chunk(self, data):
        self.wfile.write(('%x\r\n' % len(data)).encode() + data + b'\r\n')
        self.wfile.flush()

    def await_upstream(self, operation, stream, cleanup=None):
        """Keep the client alive while upstream headers or the next bytes are pending."""
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
        self.keepalive = PING if self.path.split('?')[0] == '/v1/messages' else b': keep-alive\n\n'
        tokens = [self.headers.get('x-api-key', ''), self.headers.get('Authorization', '').removeprefix('Bearer ')]
        if self.path == '/v0/management/quota-wait':
            if not any(secrets.compare_digest(token.encode(), self.server.key.encode()) for token in tokens):
                self.json_reply(401, {'error': {'type': 'authentication_error', 'message': 'Unauthorized'}})
                return
            self.json_reply(200, self.server.snapshot())
            return
        size = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(size) if size else None
        inference = self.command == 'POST' and self.path.split('?')[0] in ('/v1/messages', '/v1/responses', '/v1/chat/completions')
        if not inference:
            self.forward(body)
            return
        if not any(secrets.compare_digest(token.encode(), key.encode()) for token in tokens for key in self.server.client_keys):
            self.json_reply(401, {'error': {'type': 'authentication_error', 'message': 'Invalid API key'}})
            return
        try:
            request = json.loads(body)
            model = request['model']
            if not isinstance(model, str):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            self.forward(body)
            return
        stream = bool(request.get('stream'))
        ident = secrets.token_hex(8)
        started = False
        with self.server.lock:
            self.server.jobs[ident] = {'model': model, 'state': 'running', 'since': time.time(), 'retry_at': None}
        try:
            while True:
                try:
                    self.server.refresh_aliases()
                    reset = quota_wait(self.server.accounts(), model, self.server.aliases)
                except (OSError, ValueError, http.client.HTTPException):
                    reset = None
                if reset:
                    with self.server.lock:
                        self.server.jobs[ident].update(state='waiting', retry_at=reset)
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
                conn, response = self.await_upstream(lambda: self.open_upstream(body), stream,
                                                     cleanup=lambda result: result[0].close())
                started = self.response_started
                try:
                    if response.status in (429, 403, 503):
                        error = response.read()
                        try:
                            reset = quota_wait(self.server.accounts(), model, self.server.aliases)
                        except (OSError, ValueError, http.client.HTTPException):
                            reset = None
                        if reset:
                            continue
                        self.deliver(response, error, started, stream)
                        return
                    self.deliver(response, None, started, stream)
                    return
                finally:
                    conn.close()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self.close_connection = True
        except (OSError, http.client.HTTPException):
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
                self.chunk(data)
        self.wfile.write(b'0\r\n\r\n')
        self.wfile.flush()

    def forward(self, body):
        conn = None
        try:
            conn, response = self.open_upstream(body)
            self.deliver(response, None)
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
    server.verifications_path = controller.verification_path
    server.serve_forever()


if __name__ == '__main__':
    main()
