import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harbor_activity import HarborActivity, key_id
from tokenharbor import TokenHarbor


class HarborActivityTests(unittest.TestCase):
    def test_maps_completed_requests_to_one_key_without_saving_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'activity.json'
            activity = HarborActivity(path)
            keys = {'first': 'thk_first-secret', 'second': 'thk_second-secret'}
            records = [
                {'execution_id': '1', 'auth_index': 'first', 'timestamp': '2026-10-11T01:00:00Z', 'failed': False},
                {'execution_id': '2', 'auth_index': 'second', 'timestamp': '2026-10-11T01:01:00Z',
                 'failed': True, 'fail': {'status_code': 429}},
                {'execution_id': '3', 'auth_index': 'google', 'timestamp': '2026-10-11T01:02:00Z'},
            ]
            self.assertTrue(activity.observe(records, keys))
            self.assertFalse(activity.observe(records, keys))
            self.assertEqual(activity.status(keys['first'])['status'], 0)
            self.assertEqual(activity.status(keys['second'])['status'], 429)
            self.assertEqual(activity.state['latest']['key_id'], key_id(keys['second']))
            self.assertNotIn('thk_first-secret', path.read_text('utf-8'))
            self.assertNotIn('thk_second-secret', path.read_text('utf-8'))

    def test_proxy_auth_indexes_match_only_configured_keys(self):
        controller = Mock()
        controller.request.return_value = {'claude-api-key': [
            {'api-key': 'thk_one-secret', 'auth-index': 'one'},
            {'api-key': 'thk_other-secret', 'auth-index': 'other'},
        ]}
        client = TokenHarbor(controller, None)
        client.keys = lambda: ['thk_one-secret']
        self.assertEqual(client.auth_keys(), {'one': 'thk_one-secret'})


if __name__ == '__main__':
    unittest.main()
