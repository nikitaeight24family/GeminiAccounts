import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Controller


class QuotaStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.c = Controller(data_dir=self.temp.name)
        self.account = {'name': 'a', 'auth_index': 'idx', 'project_id': 'project', 'disabled': False}
        self.calls = []
        def request(*args):
            self.calls.append(args)
            return {'status_code': 200, 'body': '{}'}
        self.c.request = request
        self.data = {'groups': [{'kind': kind, 'buckets': [
            {'window': '5h', 'remaining': 1}, {'window': 'weekly', 'remaining': 1}]} for kind in ('gemini', 'claude')]}
        self.data['models'] = {'gemini-3-flash': {}, 'gpt-oss-120b-medium': {}}
    def tearDown(self): self.temp.cleanup()
    def test_once_per_provider_and_survives_restart(self):
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=820), [])
        self.assertEqual(len(self.c.start_full_quota_windows(self.account, self.data, now=1000)), 2)
        for call in self.calls:
            self.assertEqual(call[2]['url'], 'https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent')
            self.assertEqual(call[2]['auth_index'], 'idx')
            self.assertEqual(json.loads(call[2]['data'])['request']['generationConfig']['maxOutputTokens'], 1)
            self.assertEqual(json.loads(call[2]['data'])['request']['contents'][0]['parts'][0]['text'], 'Привет')
            self.assertIn(json.loads(call[2]['data'])['model'], ('gemini-3-flash', 'gpt-oss-120b-medium'))
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1100), [])
        restarted = Controller(data_dir=self.temp.name); restarted.request = self.c.request
        self.assertEqual(restarted.start_full_quota_windows(self.account, self.data, now=1200), [])
        self.assertEqual(len(self.calls), 2)
    def test_only_fresh_full_quota_and_available_week(self):
        self.data['groups'][0]['buckets'][0]['remaining'] = .999
        self.data['groups'][1]['buckets'][1]['remaining'] = 0
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1000), [])
        self.assertEqual(self.calls, [])
    def test_no_expensive_fallback_if_cheap_models_are_missing(self):
        self.data['models'] = {'claude-sonnet-4-6': {}, 'gemini-3.8-flash-high': {}}
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1000), [])
        self.assertEqual(self.calls, [])
    def test_excluded_accounts_are_not_probed(self):
        self.account['access_issue'] = 'verification'
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1000), [])
        self.account.pop('access_issue'); self.account['disabled'] = True
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1000), [])
    def test_failed_old_endpoint_probes_do_not_block_working_endpoint(self):
        self.c.quota_starts['a:gemini'] = {'armed': False, 'failures': 3,
            'status': 429, 'attempt_at': 900, 'full_since': 500}
        result = self.c.start_full_quota_windows(self.account, self.data, now=1000)
        self.assertEqual(result, [{'kind': 'gemini', 'status': 200}])
        self.assertEqual(self.c.quota_starts['a:gemini']['endpoint'], 'daily')
    def test_partial_then_restored_starts_new_window(self):
        self.c.start_full_quota_windows(self.account, self.data, now=820)
        self.c.start_full_quota_windows(self.account, self.data, now=1000)
        for group in self.data['groups']: group['buckets'][0]['remaining'] = .5
        self.c.start_full_quota_windows(self.account, self.data, now=2000)
        for group in self.data['groups']: group['buckets'][0]['remaining'] = 1
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=18820), [])
        self.assertEqual(len(self.c.start_full_quota_windows(self.account, self.data, now=19000)), 2)
    def test_failure_has_backoff_and_attempt_limit(self):
        self.c.request = lambda *args: {'status_code': 429, 'body': '{}'}
        self.c.start_full_quota_windows(self.account, self.data, now=820)
        self.c.start_full_quota_windows(self.account, self.data, now=1000)
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1100), [])
        self.assertEqual(len(self.c.start_full_quota_windows(self.account, self.data, now=1600)), 2)
        self.assertEqual(len(self.c.start_full_quota_windows(self.account, self.data, now=2200)), 2)
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=2800), [])
    def test_three_minutes_grace_and_real_usage_cancels_only_its_family(self):
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1000), [])
        self.assertEqual(self.c.start_full_quota_windows(self.account, self.data, now=1179), [])
        result = self.c.start_full_quota_windows(self.account, self.data, now=1180, last_used={'claude': 1100})
        self.assertEqual(result, [{'kind': 'gemini', 'status': 200}])
        self.assertEqual(len(self.calls), 1)
    def test_partial_quota_cancels_grace_and_restart_keeps_deadline(self):
        self.c.start_full_quota_windows(self.account, self.data, now=1000)
        restarted = Controller(data_dir=self.temp.name); restarted.request = self.c.request
        self.assertEqual(restarted.start_full_quota_windows(self.account, self.data, now=1179), [])
        for group in self.data['groups']: group['buckets'][0]['remaining'] = .99
        self.assertEqual(restarted.start_full_quota_windows(self.account, self.data, now=1180), [])
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
