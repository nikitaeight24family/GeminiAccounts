import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Controller, AccountError, dpapi


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(data_dir=self.temp.name)
        self.items = [{'name': 'a', 'disabled': False}, {'name': 'b', 'disabled': True}]
        self.controller.accounts = lambda: [dict(a) for a in self.items]
        self.controller._set_disabled = self.set_disabled

    def tearDown(self):
        self.temp.cleanup()

    def set_disabled(self, account, disabled):
        next(a for a in self.items if a['name'] == account['name'])['disabled'] = disabled

    def test_select_and_restore_pool_preserves_all_logins(self):
        self.controller.route('b')
        self.assertEqual([a['disabled'] for a in self.items], [True, False])
        self.assertEqual(self.controller.preferences['selected'], 'b')
        self.controller.route()
        self.assertEqual([a['disabled'] for a in self.items], [False, False])
        self.assertEqual(len(self.items), 2)

    def test_failure_rolls_back_even_if_failed_request_committed(self):
        failed = False
        def ambiguous(account, disabled):
            nonlocal failed
            self.set_disabled(account, disabled)
            if account['name'] == 'a' and disabled and not failed:
                failed = True
                raise AccountError('failure after commit')
        self.controller._set_disabled = ambiguous
        with self.assertRaises(AccountError):
            self.controller.route('b')
        self.assertEqual([a['disabled'] for a in self.items], [False, True])
        self.assertEqual(self.controller.preferences['mode'], 'pool')

    def test_missing_selection_does_not_change_accounts(self):
        with self.assertRaises(AccountError):
            self.controller.route('unknown')
        self.assertEqual([a['disabled'] for a in self.items], [False, True])

    def test_new_login_keeps_selected_account(self):
        self.controller.route('a')
        self.controller.login_accounts_before = {'a', 'b'}
        self.controller.check_verified_account = lambda *a, **kw: {'status': 'ok'}
        self.items.append({'name': 'new', 'disabled': False})
        self.controller.reconcile_new_login()
        self.assertEqual([a['disabled'] for a in self.items], [False, True, True])

    def test_new_login_probes_only_new_identity_and_returns_confirmation(self):
        self.controller.login_accounts_before = {'a', 'b'}
        self.items.append({'name': 'new', 'disabled': False})
        called = []
        def check(account, refresh_link=False):
            called.append((account['name'], refresh_link))
            return {'access_issue': 'verification', 'verification_url': 'https://accounts.google.com/signin/test'}
        self.controller.check_verified_account = check
        result = self.controller.reconcile_new_login()
        self.assertEqual(called, [('new', True)])
        self.assertEqual(result[0]['access_issue'], 'verification')

    def test_confirmation_enables_saved_disabled_account(self):
        account = {'name': 'b', 'disabled': True, 'auth_index': 'test'}
        self.controller.request = lambda *args: {'status_code': 200, 'body': '{}'}
        self.controller.check_verified_account(account)
        self.assertFalse(self.items[1]['disabled'])

    def test_ui_does_not_receive_tokens(self):
        self.controller.request = lambda *a: {'files': [{'provider': 'antigravity', 'name': 'a',
            'email': 'a@example.com', 'access_token': 'secret', 'refresh_token': 'secret'}]}
        del self.controller.accounts
        self.assertNotIn('access_token', self.controller.accounts()[0])
        self.assertNotIn('refresh_token', self.controller.accounts()[0])

    def test_verification_survives_status_refresh_restart_and_failed_check(self):
        del self.controller.accounts
        del self.controller._set_disabled
        item = {'provider': 'antigravity', 'name': 'pending', 'auth_index': 'idx',
                'status_message': '{"error":{"details":[{"reason":"VALIDATION_REQUIRED","metadata":{"validation_url":"https://accounts.google.com/signin/continue?test=1"}}]}}'}
        self.controller.request = lambda *args: {'files': [item]}
        self.assertEqual(self.controller.accounts()[0]['access_issue'], 'verification')
        item['status_message'] = ''
        item['status'] = 'active'
        self.assertEqual(self.controller.accounts()[0]['access_issue'], 'verification')
        restarted = Controller(data_dir=self.temp.name)
        restarted.request = lambda *args: {'files': [item]}
        account = restarted.accounts()[0]
        self.assertEqual(account['access_issue'], 'verification')
        self.assertIn('accounts.google.com', account['verification_url'])
        self.assertNotIn(b'accounts.google.com', restarted.verification_path.read_bytes())
        fresh_body = '{"error":{"details":[{"reason":"VALIDATION_REQUIRED","metadata":{"validation_url":"https://accounts.google.com/signin/continue?test=2"}}]}}'
        restarted.request = lambda *args: {'status_code': 403, 'body': fresh_body}
        self.assertTrue(restarted.refresh_verification_url(account)['verification_url'].endswith('test=2'))
        self.assertTrue(restarted.verifications['pending']['verification_url'].endswith('test=2'))
        restarted.request = lambda *args: {'status_code': 429, 'body': '{}'}
        with self.assertRaises(AccountError):
            restarted.retry_verified_account(account)
        self.assertIn('pending', restarted.verifications)
        restarted.request = lambda *args: {'status_code': 200, 'body': '{}'}
        restarted.retry_verified_account(account)
        self.assertNotIn('pending', restarted.verifications)

    def test_google_url_validation(self):
        self.controller.request = lambda *a: {'url': 'https://accounts.google.com/o/oauth2/auth?state=test', 'state': 'test'}
        url, state = self.controller.begin_login()
        self.assertIn('select_account', url)
        self.assertEqual(state, 'test')
        self.controller.request = lambda *a: {'url': 'https://example.com/login', 'state': 'test'}
        with self.assertRaises(AccountError):
            self.controller.begin_login()

    def test_pool_does_not_enable_unverified_account(self):
        self.items[0]['access_issue'] = 'verification'
        self.controller.route()
        self.assertTrue(self.items[0]['disabled'])
        self.assertFalse(self.items[1]['disabled'])
        with self.assertRaises(AccountError):
            self.controller.route('a')

    def test_quarantine_preserves_confirmation_and_restores_after_success(self):
        c = Controller(data_dir=self.temp.name)
        item = {'name': 'pending', 'provider': 'antigravity', 'disabled': False, 'auth_index': 'index'}
        c.remember_verification('pending', {'access_issue': 'verification', 'verification_url': 'https://accounts.google.com/signin/test'})
        calls = []
        def request(path, method='GET', payload=None):
            calls.append((path, payload))
            if path == '/auth-files': return {'files': [item.copy()]}
            if path == '/api-call': return {'status_code': 200, 'body': '{}'}
            if path == '/auth-files/status': item['disabled'] = payload['disabled']
            return {}
        c.request = request
        result = c.accounts()[0]
        self.assertTrue(result['disabled'])
        self.assertEqual(result['access_issue'], 'verification')
        self.assertTrue(c.verifications['pending']['auto_disabled'])
        c.retry_verified_account(result)
        self.assertFalse(item['disabled'])
        self.assertNotIn('pending', c.verifications)

    def test_windows_key_protection(self):
        encrypted = dpapi(b'test-local-management-key')
        self.assertNotIn(b'test-local-management-key', encrypted)
        self.assertEqual(dpapi(encrypted, decrypt=True), b'test-local-management-key')

    def test_quota_missing_fraction_is_not_zero(self):
        result = Controller.parse_quotas({'models': {'available': {'quotaInfo': {'remainingFraction': .67}},
            'empty': {'quotaInfo': {'remainingFraction': 0}}, 'unknown': {'quotaInfo': {'resetTime': '2026-10-07T00:00:00Z'}},
            'bad': {'quotaInfo': {'remainingFraction': float('nan')}}, 'out_of_range': {'quotaInfo': {'remainingFraction': 8}}}})
        self.assertEqual(result['available']['remaining'], .67)
        self.assertEqual(result['empty']['remaining'], 0)
        self.assertIsNone(result['unknown']['remaining'])
        self.assertIsNone(result['bad']['remaining'])
        self.assertIsNone(result['out_of_range']['remaining'])

    def test_weekly_and_five_hour_buckets_remain_independent(self):
        groups = Controller.parse_groups({'groups': [{'displayName': 'Claude and GPT models', 'buckets': [
            {'window': '5h', 'remainingFraction': 0, 'resetTime': '2026-10-07T00:00:00Z'},
            {'window': 'weekly', 'remainingFraction': .24, 'resetTime': '2026-10-13T00:00:00Z'}]}]})
        self.assertEqual(groups[0]['kind'], 'claude')
        self.assertEqual(groups[0]['buckets'][0]['remaining'], 0)
        self.assertEqual(groups[0]['buckets'][1]['remaining'], .24)
        self.assertNotEqual(groups[0]['buckets'][0]['reset'], groups[0]['buckets'][1]['reset'])


if __name__ == '__main__':
    unittest.main()
