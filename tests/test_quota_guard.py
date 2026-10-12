import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from quota_guard import QuotaGuard

class QuotaGuardTests(unittest.TestCase):
    def test_wait_recovery_checks_blocked_accounts_without_reserves_and_throttles_polls(self):
        auth = Mock()
        blocked = {'name': 'one', 'cooldowns': [{'reason': 'quota', 'http_status': 429}]}
        auth.accounts.return_value = [blocked, {'name': 'available'},
            {'name': 'paused', 'disabled': True, 'cooldowns': [{'reason': 'quota'}]},
            {'name': 'auth-error', 'cooldowns': [{'reason': 'error', 'http_status': 401}]}]
        def quota(account):
            account['cooldowns'] = []
            return {'allowed': True}
        auth.quota.side_effect = quota
        with patch('quota_guard.ChatGPTAuth', return_value=auth), patch('quota_guard.time.monotonic', return_value=100):
            guard = QuotaGuard(SimpleNamespace(preferences={}))
            self.assertTrue(guard.recover_waiting('gpt-test'))
            auth.quota.assert_called_once_with(blocked)
            self.assertFalse(guard.recover_waiting('gpt-test'))
            self.assertFalse(guard.recover_waiting('gemini-test'))
            self.assertEqual(auth.accounts.call_count, 1)

    def test_each_request_reads_current_reserve_and_refreshes_only_configured_enabled_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preferences.json'
            path.write_text(json.dumps({'quota-floors': {'one': {'openai': {'5h': 75}}}}))
            c = SimpleNamespace(settings_path=path, preferences={})
            auth = Mock()
            auth.accounts.return_value = [{'name': 'one'}, {'name': 'other'}, {'name': 'paused', 'disabled': True}]
            auth.quota.return_value = {'windows': [{'label':'5h','remaining':65}]}
            with patch('quota_guard.ChatGPTAuth', return_value=auth):
                guard = QuotaGuard(c)
                guard('gpt-test')
                auth.quota.assert_called_once_with({'name':'one'})
                self.assertEqual(c.preferences['quota-floors']['one']['openai']['5h'],75)
                auth.reset_mock()
                path.write_text(json.dumps({'quota-floors': {}}))
                guard('gpt-test')
                auth.quota.assert_not_called()
                guard('gemini-test')
                auth.accounts.assert_not_called()

    def test_unavailable_usage_applies_fail_closed_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'preferences.json'
            path.write_text(json.dumps({'quota-floors': {'one': {'openai': {'5h':75}}}}))
            c=SimpleNamespace(settings_path=path, preferences={})
            auth=Mock();auth.accounts.return_value=[{'name':'one'}];auth.quota.return_value={'error':'unavailable'}
            with patch('quota_guard.ChatGPTAuth',return_value=auth), patch('quota_guard.sync_quota_limits') as sync:
                QuotaGuard(c)('gpt-test')
                sync.assert_called_once_with(c,{'name':'one'},[])
