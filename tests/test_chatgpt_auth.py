import base64
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import AccountError
from backend import Controller
from chatgpt_auth import ChatGPTAuth, gateway_credential
from isolated_browser import open_isolated
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

    def test_reset_list_filters_unavailable_and_redeems_selected_credit_once(self):
        controller = Mock()
        requests = []
        def request(_path, _method, payload):
            requests.append(payload)
            if _path == '/routing/cooldown/reset':
                return {'status': 'ok', 'auth_index': payload['auth_index']}
            if payload['url'].endswith('/usage'):
                return {'status_code': 200, 'body': json.dumps({'rate_limit_reset_credits': {'available_count': 1}})}
            if payload['method'] == 'GET':
                return {'status_code': 200, 'body': json.dumps({'credits': [
                    {'id': 'ready', 'reset_type': 'codex_rate_limits', 'status': 'available',
                     'expires_at': '2099-01-01T00:00:00Z'},
                    {'id': 'used', 'reset_type': 'codex_rate_limits', 'status': 'redeemed'},
                    {'id': 'other', 'reset_type': 'future_reset_type', 'status': 'available'}]})}
            return {'status_code': 200, 'body': json.dumps({'code': 'reset', 'windows_reset': 2})}
        controller.request.side_effect = request
        account = {'auth_index': 'index-1', 'account': 'account-123'}
        auth = ChatGPTAuth(controller)
        self.assertEqual(auth.use_reset_credit(account), 2)
        self.assertEqual([request.get('method') for request in requests], ['GET', 'GET', 'POST', None])
        self.assertEqual(set(json.loads(requests[-2]['data'])), {'redeem_request_id'})
        self.assertEqual(requests[-2]['header']['ChatGPT-Account-Id'], 'account-123')

    def test_unavailable_reset_is_never_consumed(self):
        controller = Mock()
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({'credits': []})}
        with self.assertRaises(AccountError):
            ChatGPTAuth(controller).use_reset_credit({'auth_index': 'index-1'})
        self.assertEqual(controller.request.call_count, 1)

    def test_reset_timeout_and_unconfirmed_result_never_retry_or_clear_cooldown(self):
        for response in (AccountError('timeout'), {'status_code': 200, 'body': '{}'},
                         {'status_code': 200, 'body': 'broken json'},
                         {'status_code': 429, 'body': '{}'}):
            with self.subTest(response=response):
                controller = Mock()
                controller.request.side_effect = [response]
                auth = ChatGPTAuth(controller)
                with patch.object(auth, 'quota', return_value={'reset_options': [{'id': 'ready'}]}):
                    with self.assertRaises(AccountError):
                        auth.use_reset_credit({'auth_index': 'one'})
                self.assertEqual(controller.request.call_count, 1)

    def test_expired_or_inapplicable_resets_are_hidden(self):
        controller = Mock()
        credit = {'id': 'old', 'status': 'available', 'reset_type': 'codex_rate_limits',
                  'expires_at': '2000-01-01T00:00:00Z'}
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({'credits': [credit]})}
        self.assertEqual(ChatGPTAuth(controller).list_reset_credits({'auth_index': 'one'}), [])
        credit['expires_at'] = '2099-01-01T00:00:00Z'
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({
            'credits': [credit], 'applicable_available_count': 0})}
        self.assertEqual(ChatGPTAuth(controller).list_reset_credits({'auth_index': 'one'}), [])

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

    def test_signin_uses_gateway_oauth_and_rejects_other_hosts(self):
        controller = Mock()
        controller.request.return_value = {
            'url': 'https://auth.openai.com/oauth/authorize?state=one', 'state': 'one'}
        auth = ChatGPTAuth(controller)
        self.assertEqual(auth.begin_login()[1], 'one')
        controller.request.assert_called_with('/codex-auth-url?is_webui=true')
        controller.request.return_value = {
            'url': 'https://auth.openai.com.evil.example/oauth/authorize', 'state': 'two'}
        with self.assertRaises(AccountError):
            auth.begin_login()

    def test_each_browser_signin_gets_a_separate_private_profile(self):
        with patch('isolated_browser.find_browser', return_value=(Path('msedge.exe'), 'edge')):
            with patch('isolated_browser.subprocess.Popen') as popen:
                open_isolated('https://auth.openai.com/oauth/authorize?state=one')
                open_isolated('https://auth.openai.com/oauth/authorize?state=two')
        first = popen.call_args_list[0].args[0]
        second = popen.call_args_list[1].args[0]
        self.assertIn('--inprivate', first)
        self.assertNotEqual(next(v for v in first if v.startswith('--user-data-dir=')),
                            next(v for v in second if v.startswith('--user-data-dir=')))
        self.assertTrue(first[-1].startswith('https://auth.openai.com/'))

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
