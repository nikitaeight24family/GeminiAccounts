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
from chatgpt_auth import ChatGPTAuth, gateway_credential, same_oauth_session
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
    def test_shared_codex_session_is_rejected_before_gateway_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'import.json'
            codex = Path(directory) / 'auth.json'
            raw = {'auth_mode': 'chatgpt', 'tokens': {'id_token': fake_jwt(),
                'access_token': 'access-test', 'refresh_token': 'shared-refresh', 'account_id': 'account-123'}}
            source.write_text(json.dumps(raw))
            codex.write_text(json.dumps(raw))
            controller = Mock()
            with self.assertRaisesRegex(AccountError, 'separate session'):
                ChatGPTAuth(controller).import_file(source, codex_auth_path=codex)
            controller.upload_auth_file.assert_not_called()
            controller.request.assert_not_called()

    def test_session_comparison_recognizes_rotation_and_keeps_distinct_logins_separate(self):
        def token(session):
            payload = base64.urlsafe_b64encode(json.dumps({'session_id': session}).encode()).decode().rstrip('=')
            return 'header.' + payload + '.signature'
        first = {'access_token': token('same-session'), 'refresh_token': 'old-refresh'}
        rotated = {'tokens': {'access_token': token('same-session'), 'refresh_token': 'new-refresh'}}
        self.assertTrue(same_oauth_session(first, rotated))
        self.assertFalse(same_oauth_session(first, {'access_token': token('separate-session'), 'refresh_token': 'separate-refresh'}))

    def test_duplicate_gateway_session_is_rejected_without_replacing_existing_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'import.json'
            raw = {'auth_mode': 'chatgpt', 'tokens': {'id_token': fake_jwt(),
                'access_token': 'access-test', 'refresh_token': 'shared-refresh', 'account_id': 'account-123'}}
            source.write_text(json.dumps(raw))
            controller = Mock()
            controller.request.side_effect = [
                {'files': [{'provider': 'codex', 'name': 'codex-browser-login.json', 'email': 'person@example.com'}]},
                {'refresh_token': 'shared-refresh'}]
            with self.assertRaisesRegex(AccountError, 'already connected'):
                ChatGPTAuth(controller).import_file(source, codex_auth_path=Path(directory) / 'missing.json')
            controller.upload_auth_file.assert_not_called()

    def test_reimport_cannot_overwrite_rotated_tokens_but_separate_login_can_replace_entry(self):
        import hashlib
        def access(session):
            encoded = base64.urlsafe_b64encode(json.dumps({'session_id': session}).encode()).decode().rstrip('=')
            return 'header.' + encoded + '.signature'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'import.json'
            raw = {'auth_mode': 'chatgpt', 'tokens': {'id_token': fake_jwt(),
                'access_token': access('old-session'), 'refresh_token': 'old-refresh', 'account_id': 'account-123'}}
            source.write_text(json.dumps(raw))
            name = 'codex-import-' + hashlib.sha256(b'account-123').hexdigest()[:16] + '.json'
            connected = {'files': [{'provider': 'codex', 'name': name, 'email': 'person@example.com'}]}
            controller = Mock()
            controller.request.side_effect = [connected,
                {'access_token': access('old-session'), 'refresh_token': 'renewed-refresh'}]
            importer = ChatGPTAuth(controller)
            with self.assertRaisesRegex(AccountError, 'old copy'):
                importer.import_file(source, codex_auth_path=Path(directory) / 'missing.json')
            controller.upload_auth_file.assert_not_called()
            raw['tokens']['access_token'] = access('new-session')
            raw['tokens']['refresh_token'] = 'new-session-refresh'
            source.write_text(json.dumps(raw))
            controller.request.side_effect = [connected,
                {'access_token': access('old-session'), 'refresh_token': 'renewed-refresh'}, connected]
            importer.import_file(source, codex_auth_path=Path(directory) / 'missing.json')
            controller.upload_auth_file.assert_called_once()

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

    def test_subscription_comes_from_live_quota_without_inventing_free(self):
        controller = Mock()
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({'plan_type': 'pro'})}
        self.assertEqual(ChatGPTAuth(controller).quota({'auth_index': 'one'})['plan_type'], 'pro')
        controller.request.return_value['body'] = '{}'
        self.assertIsNone(ChatGPTAuth(controller).quota({'auth_index': 'one'})['plan_type'])

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
            connected = {'files': [{
                'name': 'codex-import-e7f930c85d25ab68.json',
                'provider': 'codex', 'email': 'person@example.com', 'disabled': False}]}
            importer = ChatGPTAuth(controller)
            # Use the generated name in the mock response, avoiding a second credential copy.
            import hashlib
            connected['files'][0]['name'] = (
                'codex-import-' + hashlib.sha256(b'account-123').hexdigest()[:16] + '.json')
            controller.request.side_effect = [{'files': []}, connected]
            email, accounts = importer.import_file(path, codex_auth_path=Path(directory) / 'missing.json')
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
            if _path == '/reset-quota':
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
        controller.request.assert_called_with('/reset-quota', 'POST', {'auth_index': 'index-1'})

    def test_full_provider_reset_clears_old_gateway_block_and_updates_account(self):
        controller = Mock()
        controller.request.side_effect = [
            {'status_code': 200, 'body': json.dumps({'rate_limit': {'allowed': True, 'limit_reached': False,
                'primary_window': {'used_percent': 0, 'limit_window_seconds': 18000},
                'secondary_window': {'used_percent': 0, 'limit_window_seconds': 604800}}})},
            {'status': 'ok', 'auth_index': 'one'},
            {'files': [{'provider': 'codex', 'auth_index': 'one', 'status': 'active',
                        'unavailable': False, 'cooldowns': []}]}]
        account = {'auth_index': 'one', 'unavailable': True, 'cooldowns': [
            {'reason': 'credential_quota'}, {'reason': 'quota', 'http_status': 429}]}
        quota = ChatGPTAuth(controller).quota(account)
        self.assertTrue(quota['allowed'])
        self.assertEqual(account['cooldowns'], [])
        self.assertFalse(account['unavailable'])
        self.assertEqual(controller.request.call_args_list[1].args, ('/reset-quota', 'POST', {'auth_index': 'one'}))

    def test_recovery_does_not_clear_auth_errors_rate_limits_or_partly_used_quota(self):
        for overrides, blocks in [({'allowed': False}, [{'reason': 'quota'}]),
                ({'windows': [{'label': '5h', 'remaining': 99}, {'label': '1w', 'remaining': 100}]}, [{'reason': 'quota'}]),
                ({}, [{'reason': 'quota', 'http_status': 401}]),
                ({}, [{'reason': 'rate_limit'}])]:
            with self.subTest(overrides=overrides, blocks=blocks):
                controller = Mock()
                quota = {'allowed': True, 'limit_reached': False,
                         'windows': [{'label': '5h', 'remaining': 100}, {'label': '1w', 'remaining': 100}]}
                quota.update(overrides)
                self.assertFalse(ChatGPTAuth(controller).recover_reset_quota({'auth_index': 'one', 'cooldowns': blocks}, quota))
                controller.request.assert_not_called()

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

    def test_chatgpt_waits_only_for_its_own_pool_and_wakes_on_new_account(self):
        files = [{'provider': 'codex', 'disabled': False, 'cooldowns': [
            {'scope': 'credential', 'http_status': 429, 'reason': 'quota',
             'retry_at': '2099-01-01T00:00:00Z'}]},
            {'provider': 'antigravity', 'disabled': False, 'cooldowns': []}]
        self.assertIsNotNone(quota_wait(files, 'gpt-6-sol', {}))
        self.assertIsNone(quota_wait(files, 'gemini-3-flash', {}))
        files.append({'provider': 'codex', 'disabled': False, 'cooldowns': []})
        self.assertIsNone(quota_wait(files, 'gpt-6-sol', {}))

    def test_chatgpt_probe_has_grace_is_persisted_and_skips_expensive_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            controller.models = Mock(return_value=['gpt-5.6-luna', 'gpt-6-astra'])
            controller.request = Mock(return_value={'status_code': 200, 'body': 'event: response.completed\n'})
            auth = ChatGPTAuth(controller)
            account = {'name': 'one', 'auth_index': 'one', 'disabled': False}
            quota = {'windows': [{'label': '5h', 'remaining': 100}, {'label': '1w', 'remaining': 100}]}
            self.assertIsNone(auth.start_full_quota_window(account, quota, now=1000))
            self.assertIsNone(auth.start_full_quota_window(account, quota, now=1179))
            self.assertEqual(auth.start_full_quota_window(account, quota, now=1180), 200)
            payload = controller.request.call_args.args[2]
            self.assertEqual(payload['auth_index'], 'one')
            request = json.loads(payload['data'])
            self.assertEqual(request['model'], 'gpt-5.6-luna')
            self.assertEqual(request['max_output_tokens'], 16)
            restarted = Controller(data_dir=directory)
            restarted.models = controller.models
            restarted.request = controller.request
            self.assertIsNone(ChatGPTAuth(restarted).start_full_quota_window(account, quota, now=1300))
            self.assertEqual(controller.request.call_count, 1)
            controller.models.return_value = ['gpt-6-astra']
            other = {**account, 'name': 'other'}
            auth.start_full_quota_window(other, quota, now=2000)
            self.assertIsNone(auth.start_full_quota_window(other, quota, now=2180))
            self.assertEqual(controller.request.call_count, 1)

    def test_chatgpt_probe_real_usage_cancels_grace_and_weekly_block_skips_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            controller.request = Mock()
            auth = ChatGPTAuth(controller)
            account = {'name': 'one', 'auth_index': 'one', 'success': 10}
            quota = {'windows': [{'label': '5h', 'remaining': 100}, {'label': '1w', 'remaining': 100}]}
            auth.start_full_quota_window(account, quota, now=1000)
            account['success'] = 11
            self.assertIsNone(auth.start_full_quota_window(account, quota, now=1180))
            quota['windows'][1]['remaining'] = 0
            self.assertIsNone(auth.start_full_quota_window(account, quota, now=20000))
            controller.request.assert_not_called()

    def test_chatgpt_rotation_ranks_available_nearest_reset_before_exhausted_and_leaves_google_alone(self):
        import time
        controller = Mock()
        now = time.time()
        def account(name, remaining, reset):
            return {'name': name, 'provider': 'codex', 'disabled': False, 'quota': {'windows': [
                {'label': '5h', 'remaining': remaining, 'reset_at': now + reset},
                {'label': '1w', 'remaining': 100, 'reset_at': now + 600000}]}}
        accounts = [account('later', 90, 5000), account('empty', 0, 100), account('first', 70, 1000)]
        controller.request.side_effect = lambda path, *args: {'files': accounts} if path == '/auth-files' else {'strategy': 'fill-first'}
        self.assertTrue(ChatGPTAuth(controller).apply_reset_priority(accounts))
        changes = [call.args[2] for call in controller.request.call_args_list if call.args[0] == '/auth-files/fields']
        self.assertEqual(changes, [{'name': 'first', 'priority': 3}, {'name': 'later', 'priority': 2}, {'name': 'empty', 'priority': 1}])
        controller.preferences = {'account-priorities': {'later': 9, 'empty': 999}}
        controller.request.reset_mock()
        self.assertTrue(ChatGPTAuth(controller).apply_reset_priority(accounts))
        changes = [call.args[2] for call in controller.request.call_args_list if call.args[0] == '/auth-files/fields']
        self.assertEqual([change['name'] for change in changes], ['later', 'first'])

    def test_available_account_without_5h_goes_first_until_refused_or_reserved(self):
        import time
        now = time.time()
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            timed = {'name': 'timed', 'provider': 'codex', 'quota': {'windows': [
                {'label': '5h', 'remaining': 90, 'reset_at': now + 1000},
                {'label': '1w', 'remaining': 90, 'reset_at': now + 600000}]}}
            untimed = {'name': 'untimed', 'provider': 'codex', 'status': 'active',
                       'quota': {'allowed': True, 'limit_reached': False, 'windows': [
                           {'label': '1w', 'remaining': 100, 'reset_at': now + 600000}]}}
            accounts = [timed, untimed]
            controller.preferences = {'account-priorities': {'timed': 999}}
            controller.request = Mock(side_effect=lambda path, *args:
                {'files': accounts} if path == '/auth-files' else {'strategy': 'fill-first'})
            auth = ChatGPTAuth(controller)
            self.assertTrue(auth.apply_reset_priority(accounts))
            self.assertGreater(untimed['priority'], timed['priority'])
            for change in ({'unavailable': True}, {'status': 'error'},
                           {'cooldowns': [{'scope': 'credential', 'reason': 'quota', 'retry_at': '2099-01-01T00:00:00Z'}]}):
                with self.subTest(change=change):
                    untimed.update(change)
                    auth.apply_reset_priority(accounts)
                    self.assertGreater(timed['priority'], untimed['priority'])
                    for key in change:
                        untimed.pop(key)
            untimed['quota']['allowed'] = False
            auth.apply_reset_priority(accounts)
            self.assertGreater(timed['priority'], untimed['priority'])
            untimed['quota']['allowed'] = True
            controller.preferences['quota-floors'] = {'untimed': {'openai': {'weekly': 100}}}
            auth.apply_reset_priority(accounts)
            self.assertGreater(timed['priority'], untimed['priority'])
            controller.preferences['quota-floors'] = {}
            untimed['disabled'] = True
            auth.apply_reset_priority(accounts)
            self.assertEqual(timed['priority'], 1)

    def test_weekly_only_usage_does_not_invent_a_5h_window(self):
        controller = Mock()
        controller.preferences = {}
        controller.request.return_value = {'status_code': 200, 'body': json.dumps({
            'plan_type': 'plus', 'rate_limit': {'allowed': True, 'limit_reached': False,
                'primary_window': {'used_percent': 0, 'limit_window_seconds': 604800},
                'secondary_window': None}})}
        quota = ChatGPTAuth(controller).quota({'name': 'untimed', 'auth_index': 'six'})
        self.assertTrue(quota['allowed'])
        self.assertEqual(quota['windows'], [{'label': '1w', 'remaining': 100, 'reset_at': None}])

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

    def test_chatgpt_429_with_own_cooldown_resumes_when_new_account_is_added(self):
        class Gateway(MockGateway):
            def do_POST(self):
                if self.server.calls == 0:
                    self.server.files = [{'provider': 'codex', 'name': 'blocked', 'cooldowns': [
                        {'scope': 'credential', 'reason': 'quota', 'http_status': 429,
                         'retry_at': '2099-01-01T00:00:00Z'}]}]
                super().do_POST()
        backend = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        backend.files, backend.calls, backend.status = [], 0, 429
        gate = QueueServer(('127.0.0.1', 0), backend.server_address, 'admin', ['client'], {})
        gate.poll_seconds = .01
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        threading.Thread(target=gate.serve_forever, daemon=True).start()
        client = http.client.HTTPConnection(*gate.server_address, timeout=3)
        try:
            client.request('POST', '/v1/messages', json.dumps({'model': 'gpt-6-sol', 'stream': True, 'messages': []}),
                           {'x-api-key': 'client'})
            response = client.getresponse()
            from quota_queue import PING
            self.assertEqual(response.read(len(PING)), PING)
            self.assertEqual(backend.calls, 1)
            backend.status = 200
            backend.files.append({'provider': 'codex', 'name': 'new', 'cooldowns': []})
            self.assertIn(b'OK', response.read())
            self.assertEqual(backend.calls, 2)
        finally:
            client.close()
            gate.shutdown()
            gate.server_close()
            backend.shutdown()
            backend.server_close()


if __name__ == '__main__':
    unittest.main()
