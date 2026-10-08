import http.client
import json
import sys
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quota_queue import QueueServer, quota_wait, PING


def account(model='gemini', seconds=20, code=429):
    return {'provider': 'antigravity', 'name': 'a', 'cooldowns': [{
        'scope': 'model', 'model_key': model, 'reason': 'quota' if code == 429 else 'error',
        'http_status': code, 'retry_at': (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}]}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        value = {'files': self.server.files}
        if self.path == '/v0/management/oauth-model-alias' and hasattr(self.server, 'model_aliases'):
            value = {'oauth-model-alias': {'antigravity': self.server.model_aliases}}
        data = json.dumps(value).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        self.server.last_request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        self.server.calls += 1
        time.sleep(getattr(self.server, 'header_delay', 0))
        data = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"real"}}\n\n'
                b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}\n\n'
                b'event: message_stop\ndata: {"type":"message_stop"}\n\n') if self.server.status == 200 else b'{"error":{"type":"authentication_error","message":"Denied"}}'
        if self.path == '/v1/responses' and self.server.status == 200:
            data = b'event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        self.send_response(self.server.status); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Content-Length', str(len(data))); self.end_headers()
        time.sleep(getattr(self.server, 'body_delay', 0))
        self.wfile.write(data)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Mock)
        self.backend.files = [account()]; self.backend.calls = 0; self.backend.status = 200
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.gate = QueueServer(('127.0.0.1', 0), self.backend.server_address, 'admin', ['client'], {'alias': 'gemini'})
        self.gate.poll_seconds = .05
        threading.Thread(target=self.gate.serve_forever, daemon=True).start()
        self.client = http.client.HTTPConnection(*self.gate.server_address, timeout=3)
    def tearDown(self):
        self.client.close(); self.gate.shutdown(); self.gate.server_close(); self.backend.shutdown(); self.backend.server_close()
    def post(self, key='client', model='alias'):
        self.client.request('POST', '/v1/messages', json.dumps({'model': model, 'stream': True, 'messages': []}), {'x-api-key': key})
        return self.client.getresponse()
    def test_wait_heartbeat_then_new_account_real_response(self):
        response = self.post()
        self.assertEqual(response.read(len(PING)), PING)
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(self.gate.snapshot()['jobs'][0]['state'], 'waiting')
        self.backend.files.append({'provider': 'antigravity', 'name': 'new', 'cooldowns': []})
        data = response.read()
        self.assertIn(b'"id":"real"', data)
        self.assertIn(b'"text":"OK"', data)
        self.assertEqual(self.backend.calls, 1)
    def test_reset_automatically_resumes(self):
        self.backend.files = [account(seconds=.2)]
        response = self.post(); data = response.read()
        self.assertTrue(data.startswith(PING))
        self.assertIn(b'message_stop', data); self.assertEqual(self.backend.calls, 1)
    def test_extended_context_suffix_preserves_quota_wait_and_upstream_model(self):
        self.backend.files = [account(seconds=.15)]
        response = self.post(model='alias[1m]')
        data = response.read()
        self.assertIn(PING, data)
        self.assertIn(b'message_stop', data)
        self.assertEqual(self.backend.last_request['model'], 'alias')
    def test_responses_wait_uses_comments_and_resumes_with_real_response(self):
        self.backend.files = [account(seconds=.15)]
        self.client.request('POST', '/v1/responses', json.dumps({'model':'alias','stream':True,'input':'hello'}), {'x-api-key':'client'})
        data = self.client.getresponse().read()
        self.assertIn(b': keep-alive\n\n', data)
        self.assertNotIn(PING, data)
        self.assertIn(b'event: response.completed', data)
        self.assertEqual(self.backend.calls, 1)
    def test_resumption_keeps_heartbeats_during_delayed_headers_and_body(self):
        self.backend.files = [account(seconds=.15)]
        # Keep phases long enough for coarse / loaded CI scheduler ticks.
        self.backend.header_delay = .4
        self.backend.body_delay = .4
        self.gate.heartbeat_seconds = .04
        response = self.post()
        data = response.read()
        self.assertGreaterEqual(data.count(PING), 5)
        self.assertIn(b'"text":"OK"', data)
        self.assertEqual(data.count(b'event: message_start'), 1)
        self.assertEqual(self.backend.calls, 1)
    def test_other_model_does_not_wait(self):
        response = self.post(model='claude')
        self.assertNotIn(PING, response.read()); self.assertEqual(self.backend.calls, 1)
    def test_invalid_client_key_never_waits(self):
        response = self.post(key='wrong'); self.assertEqual(response.status, 401)
        response.read(); self.assertEqual(self.backend.calls, 0)
    def test_valid_bearer_with_stale_api_key_is_accepted(self):
        self.backend.files = []
        self.client.request('POST', '/v1/messages', json.dumps({'model': 'alias', 'stream': True}),
                            {'x-api-key': 'stale', 'Authorization': 'Bearer client'})
        response = self.client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'message_start', response.read())
    def test_verification_error_is_not_hidden_without_quota(self):
        self.backend.files = [account(code=403)]
        self.backend.status = 403
        response = self.post(); self.assertEqual(response.status, 403)
        self.assertIn(b'Denied', response.read())
    def test_disconnect_cancels_wait_without_inference(self):
        response = self.post(); response.read(len(PING))
        response.close(); self.client.close()
        until = time.time() + 2
        while self.gate.snapshot()['jobs'] and time.time() < until: time.sleep(.05)
        self.assertEqual(self.gate.snapshot()['jobs'], [])
        self.assertEqual(self.backend.calls, 0)
    def test_metadata_requires_management_key(self):
        self.client.request('GET', '/v0/management/quota-wait')
        response = self.client.getresponse(); self.assertEqual(response.status, 401); response.read()
    def test_disabled_and_nonquota_are_not_wait_reasons(self):
        a = account(); a['disabled'] = True
        self.assertIsNone(quota_wait([a], 'gemini', {}))
        self.assertIsNone(quota_wait([account(code=403)], 'gemini', {}))
    def test_known_unverified_account_does_not_prevent_quota_wait(self):
        pending = {'provider': 'antigravity', 'access_issue': 'verification', 'cooldowns': []}
        self.assertIsNotNone(quota_wait([account(), pending], 'gemini', {}))
        self.assertIsNone(quota_wait([pending], 'gemini', {}))
    def test_last_real_403_error_after_wait_is_delivered(self):
        response = self.post(); self.assertEqual(response.read(len(PING)), PING)
        self.backend.files = []
        self.backend.status = 403
        data = response.read()
        self.assertIn(b'event: error', data)
        self.assertIn(b'Denied', data)
        self.assertNotIn(b'message_start', data)
        self.assertEqual(self.backend.calls, 1)

    def test_hot_model_selection_does_not_wait_for_old_model_quota(self):
        self.backend.files = [account(model='gemini')]
        self.backend.model_aliases = [{'alias': 'alias', 'name': 'gemini-pro-agent'}]
        response = self.post()
        data = response.read()
        self.assertIn(b'"text":"OK"', data)
        self.assertNotIn(PING, data)
        self.assertEqual(self.gate.aliases['alias'], 'gemini-pro-agent')


if __name__ == '__main__': unittest.main()
