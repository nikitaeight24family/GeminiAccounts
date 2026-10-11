import base64
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import AccountError
from backend import Controller
from chatgpt_auth import ChatGPTAuth, gateway_credential
from quota_queue import QueueServer, quota_wait
from tests.test_quota_queue import Mock as MockGateway


def fake_jwt():
    payload = {'email': 'person@example.com', 'exp': 1792000000,
               'https://api.openai.com/auth': {
                   'chatgpt_account_id': 'account-123', 'chatgpt_plan_type': 'plus'}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return 'header.' + encoded + '.signature'


class ChatGPTAuthTests(unittest.TestCase):
    def test_converts_nested_codex_auth_without_api_key_or_agent_metadata(self):
        raw = {'auth_mode': 'chatgpt', 'openai_api_key': 'secret-unused',
               'agent_identity': {'private': 'secret-unused'},
               'tokens': {'id_token': fake_jwt(), 'access_token': 'access-test',
                          'refresh_token': 'refresh-test', 'account_id': 'account-123'}}
        converted = gateway_credential(raw)
        self.assertEqual(converted['type'], 'codex')
        self.assertEqual(converted['email'], 'person@example.com')
        self.assertEqual(converted['plan_type'], 'plus')
        self.assertEqual(converted['account_id'], 'account-123')
        self.assertNotIn('openai_api_key', converted)
        self.assertNotIn('agent_identity', converted)

    def test_rejects_api_key_file_and_incomplete_tokens(self):
        with self.assertRaises(AccountError):
            gateway_credential({'OPENAI_API_KEY': 'api-test'})
        with self.assertRaises(AccountError):
            gateway_credential({'auth_mode': 'chatgpt', 'tokens': {'id_token': fake_jwt()}})
        with self.assertRaises(AccountError):
            gateway_credential({'auth_mode': 'chatgpt', 'tokens': {
                'id_token': fake_jwt(), 'access_token': 'access-test',
                'refresh_token': 'refresh-test', 'account_id': 'wrong-account'}})

    def test_import_uploads_only_generated_credential_and_lists_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            path.write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {
                'id_token': fake_jwt(), 'access_token': 'access-test',
                'refresh_token': 'refresh-test', 'account_id': 'account-123'}}), 'utf-8')
            controller = Mock()
            controller.request.return_value = {'files': [{
                'name': 'codex-import-e7f930c85d25ab68.json',
                'provider': 'codex', 'email': 'person@example.com', 'disabled': False}]}
            importer = ChatGPTAuth(controller)
            # Use the generated name in the mock response, avoiding a second credential copy.
            import hashlib
            controller.request.return_value['files'][0]['name'] = (
                'codex-import-' + hashlib.sha256(b'account-123').hexdigest()[:16] + '.json')
            email, accounts = importer.import_file(path)
            self.assertEqual(email, 'person@example.com')
            self.assertEqual(len(accounts), 1)
            uploaded_name, payload = controller.upload_auth_file.call_args.args
            self.assertTrue(uploaded_name.startswith('codex-import-'))
            self.assertEqual(json.loads(payload)['type'], 'codex')
            self.assertNotIn('access-test', uploaded_name)

    def test_reads_real_window_lengths_and_reset_credits(self):
        controller = Mock()
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({
            'rate_limit': {'primary_window': {'used_percent': 25, 'limit_window_seconds': 18000,
                                               'reset_at': 1792000000},
                           'secondary_window': {'used_percent': 90, 'limit_window_seconds': 604800,
                                                'reset_at': 1792500000}},
            'rate_limit_reset_credits': {'available_count': 1}})}
        quota = ChatGPTAuth(controller).quota({'auth_index': 'index-1', 'account': 'account-123'})
        self.assertEqual([(w['label'], w['remaining']) for w in quota['windows']],
                         [('5h', 75), ('1w', 10)])
        self.assertEqual(quota['reset_credits'], 1)
        sent = controller.request.call_args.args[2]
        self.assertEqual(sent['header']['Authorization'], 'Bearer $TOKEN$')
        self.assertEqual(sent['header']['ChatGPT-Account-Id'], 'account-123')

    def test_model_choices_come_only_from_chatgpt_auth_files(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(proxy_dir=Path(directory) / 'proxy', data_dir=Path(directory) / 'data')
            def request(path, *_args):
                if path == '/auth-files':
                    return {'files': [{'name': 'one.json', 'provider': 'codex', 'disabled': False},
                                      {'name': 'google.json', 'provider': 'antigravity', 'disabled': False}]}
                return {'models': [{'id': 'gpt-6-sol'}, {'id': 'gemini-3-flash'}]}
            controller.request = request
            self.assertEqual(controller.chatgpt_model_choices(), ['gpt-6-sol'])

    def test_google_quota_does_not_hold_chatgpt_models(self):
        blocked = [{'provider': 'antigravity', 'disabled': False,
                    'cooldowns': [{'scope': 'credential', 'http_status': 429,
                                   'reason': 'quota', 'retry_at': '2099-01-01T00:00:00Z'}]}]
        self.assertIsNone(quota_wait(blocked, 'gpt-6-sol', {}))
        self.assertIsNone(quota_wait(blocked, 'claude-haiku-5-5-tokenharbor-free', {}))

    def test_chatgpt_429_is_returned_without_google_retry_loop(self):
        backend = ThreadingHTTPServer(('127.0.0.1', 0), MockGateway)
        backend.files = []
        backend.calls = 0
        backend.status = 429
        gate = QueueServer(('127.0.0.1', 0), backend.server_address,
                           'admin', ['client'], {})
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        threading.Thread(target=gate.serve_forever, daemon=True).start()
        try:
            client = http.client.HTTPConnection(*gate.server_address, timeout=3)
            client.request('POST', '/v1/messages', json.dumps({
                'model': 'gpt-6-sol', 'stream': True, 'messages': []}),
                {'x-api-key': 'client'})
            response = client.getresponse()
            self.assertEqual(response.status, 429)
            response.read()
            self.assertEqual(backend.calls, 1)
            client.close()
        finally:
            gate.shutdown()
            gate.server_close()
            backend.shutdown()
            backend.server_close()


if __name__ == '__main__':
    unittest.main()
