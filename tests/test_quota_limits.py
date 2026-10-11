import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from quota_limits import blocked_families, quota_floor, sync_quota_limits


class QuotaLimitTests(unittest.TestCase):
    def setUp(self):
        self.preferences = {'quota-floors': {'one': {'gemini': {'5h': 70}, 'claude': {'weekly': 20}}}}

    def test_boundary_means_remaining_and_windows_are_independent(self):
        groups = [{'kind': 'gemini', 'buckets': [{'window': '5h', 'remaining': .701}]},
                  {'kind': 'claude', 'buckets': [{'window': 'weekly', 'remaining': .3}]}]
        self.assertEqual(blocked_families(self.preferences, 'one', groups), set())
        groups[0]['buckets'][0]['remaining'] = .7
        self.assertEqual(blocked_families(self.preferences, 'one', groups), {'gemini'})
        groups[0]['buckets'][0]['remaining'] = .3
        self.assertEqual(blocked_families(self.preferences, 'one', groups), {'gemini'})
        self.assertEqual(quota_floor(self.preferences, 'two', 'gemini', '5h'), 0)
        self.assertEqual(blocked_families(self.preferences, 'two', groups), set())

    def test_configured_boundary_holds_unknown_quota_and_zero_is_unrestricted(self):
        self.assertEqual(blocked_families(self.preferences, 'one', []), {'gemini', 'claude'})
        self.preferences['quota-floors']['one']['gemini']['5h'] = 0
        self.assertEqual(blocked_families(self.preferences, 'one', []), {'claude'})
        self.preferences['quota-floors']['one']['claude']['weekly'] = 100
        self.assertEqual(blocked_families(self.preferences, 'one', [
            {'kind': 'claude', 'buckets': [{'window': 'weekly', 'remaining': 1}]}]), {'claude'})

    def test_native_exclusions_preserve_existing_user_rules_and_clear_only_owned(self):
        controller = SimpleNamespace(preferences=self.preferences, request=Mock())
        controller.request.return_value = {'excluded_models': ['custom-model'], 'omni_quota_exclusions': []}
        groups = [{'kind': 'gemini', 'buckets': [{'window': '5h', 'remaining': .7}]},
                  {'kind': 'claude', 'buckets': [{'window': 'weekly', 'remaining': .8}]}]
        sync_quota_limits(controller, {'name': 'one'}, groups)
        patch = controller.request.call_args.args[2]
        self.assertEqual(patch['excluded_models'], ['custom-model', 'gemini*'])
        self.assertEqual(patch['omni_quota_exclusions'], ['gemini*'])
        controller.request.reset_mock()
        controller.request.return_value = patch
        groups[0]['buckets'][0]['remaining'] = .9
        sync_quota_limits(controller, {'name': 'one'}, groups)
        self.assertEqual(controller.request.call_args.args[2]['excluded_models'], ['custom-model'])

    def test_does_not_take_ownership_of_matching_user_exclusions(self):
        controller = SimpleNamespace(preferences=self.preferences, request=Mock(return_value={
            'excluded_models': ['gemini*', 'claude*', 'gpt-oss*']}))
        sync_quota_limits(controller, {'name': 'one'}, [])
        controller.request.assert_called_once()

    def test_unconfigured_accounts_never_touch_native_metadata(self):
        controller = SimpleNamespace(preferences={}, request=Mock())
        self.assertEqual(sync_quota_limits(controller, {'name': 'one'}, []), set())
        controller.request.assert_not_called()
