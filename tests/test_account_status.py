import json
import unittest
from account_status import account_status, google_account_status, safe_detail
from ui_locale import translate


class AccountStatusTests(unittest.TestCase):
    def test_google_provider_limits_are_independent(self):
        account = {'status': 'error', 'cooldowns': [{'scope': 'model', 'reason': 'quota', 'remaining_seconds': 100}]}
        groups = [{'kind': 'gemini', 'buckets': [{'remaining': .847}, {'remaining': .234}]},
                  {'kind': 'claude', 'buckets': [{'remaining': 0}]}]
        self.assertEqual(google_account_status(account, groups)[0], 'Claude quota exhausted')
        groups[0]['buckets'][0]['remaining'] = 0
        self.assertEqual(google_account_status(account, groups)[0], 'Limit exhausted')
        groups[0]['buckets'][0]['remaining'] = .847
        groups[1]['buckets'][0]['remaining'] = .5
        self.assertEqual(google_account_status(account, groups)[0], 'Model quota restricted')

    def test_google_real_credential_problem_takes_precedence(self):
        groups = [{'kind': 'claude', 'buckets': [{'remaining': 0}]}]
        self.assertEqual(google_account_status({'status': 'blocked'}, groups)[0], 'Account blocked')
        self.assertEqual(google_account_status({'disabled': True}, groups)[0], 'Paused')

    def test_real_quota_snapshot_is_not_error(self):
        account = {'status': 'error', 'unavailable': True, 'status_message': '',
                   'cooldowns': [{'scope': 'credential', 'reason': 'credential_quota', 'retry_at': '2030-01-01T00:00:00Z'}],
                   'quota': {'windows': [{'label': '5h', 'remaining': 0, 'reset_at': 2000}]}}
        self.assertEqual(account_status(account, now=1000), ('Limit exhausted', 'warning', ''))
        self.assertEqual(translate(account_status(account, now=1000)[0], 'ru'), 'Лимит исчерпан')

    def test_block_and_auth_failures_take_precedence_over_quota(self):
        for code, label in [('account_deactivated', 'Account blocked'), ('invalid_grant', 'Sign in again'), (401, 'Sign in again'), (403, 'Access denied'), (503, 'Request error')]:
            with self.subTest(code=code):
                account = {'status': 'error', 'status_message': json.dumps({'error': {'code': code, 'message': 'Provider explanation'}}),
                           'quota': {'windows': [{'label': '5h', 'remaining': 0, 'reset_at': 2000}]}}
                self.assertEqual(account_status(account, now=1000)[:2], (label, 'error'))
                self.assertEqual(account_status(account, now=1000)[2], 'Provider explanation')

    def test_rate_limit_is_distinct_from_usage_quota(self):
        self.assertEqual(account_status({'status': 'error', 'status_message': '{"error":{"code":429,"message":"Too many requests"}}'})[:2], ('Rate limited', 'warning'))
        for code, label in [(401, 'Sign in again'), (403, 'Access denied'), (429, 'Rate limited')]:
            self.assertEqual(account_status({'status': 'error', 'cooldowns': [{'http_status': code, 'remaining_seconds': 100}]})[0], label)

    def test_unknown_states_and_causes_are_preserved(self):
        self.assertEqual(account_status({'status': 'organization_review', 'status_message': 'Contact administrator'}), ('Provider status: organization_review', 'warning', 'Contact administrator'))
        self.assertEqual(account_status({'status': 'error'})[2], 'Provider did not report the cause')

    def test_expired_gateway_timer_does_not_turn_credential_quota_into_request_error(self):
        account = {'status': 'error', 'status_message': 'credential_quota',
                   'cooldowns': [{'reason': 'credential_quota', 'retry_at': '1970-01-01T00:00:01Z'}],
                   'quota': {'windows': [{'label': '5h', 'remaining': 0, 'reset_at': 1}]}}
        self.assertEqual(account_status(account, now=1000), ('Limit exhausted', 'warning', ''))

    def test_recovery_does_not_keep_expired_quota_status(self):
        self.assertEqual(account_status({'status': 'active', 'cooldowns': [{'reason': 'quota', 'retry_at': '1970-01-01T00:00:01Z'}], 'quota': {'windows': [{'label': '5h', 'remaining': 0, 'reset_at': 1}]}}, now=1000)[0], 'Available')
        self.assertEqual(account_status({'disabled': True, 'status': 'active'})[0], 'Paused')

    def test_unknown_cooldown_does_not_become_quota(self):
        self.assertEqual(account_status({'status': 'error', 'cooldowns': [{'reason': 'maintenance', 'remaining_seconds': 300}]}), ('Waiting to retry', 'warning', 'maintenance'))

    def test_details_never_show_bearer_or_credential_tokens(self):
        result = safe_detail('access_token=secret refresh_token="secret2" Bearer secret3 sk-secret4 eyJabc.def.ghi')
        for token in ('secret', 'secret2', 'secret3', 'secret4', 'eyJabc'):
            self.assertNotIn(token, result)


if __name__ == '__main__':
    unittest.main()
