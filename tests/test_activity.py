import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activity import Activity


class ActivityTests(unittest.TestCase):
    def test_retries_are_correlated_and_secrets_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'activity.json'
            tracker = Activity(path)
            accounts = [{'name': 'a', 'auth_index': 'A'}, {'name': 'b', 'auth_index': 'B'}]
            def event(identifier, auth, failed=False, trace='request', model='gemini'):
                return {'execution_id': identifier, 'trace_id': trace, 'auth_index': auth, 'alias': model,
                    'timestamp': '2026-10-06T14:00:0' + identifier + 'Z', 'failed': failed,
                    'fail': {'status_code': 429, 'body': 'SECRET_BODY'}, 'tokens': {'total_tokens': 12},
                    'api_key': 'SECRET_KEY', 'latency_ms': 1500}
            records = [event('1', 'A', True), event('2', 'B')]
            state = tracker.ingest(records, accounts)
            self.assertEqual(state['events'][-1]['from'], 'a')
            self.assertTrue(state['events'][-1]['switch'])
            self.assertIn('429', state['events'][-1]['reason'])
            tracker.ingest(records, accounts)
            self.assertEqual(len(state['events']), 2)
            self.assertEqual(state['stats']['b']['success'], 1)
            self.assertNotIn('SECRET', path.read_text(encoding='utf-8'))
            tracker.ingest([event('3', 'A', trace='different')], accounts)
            self.assertIn('не передана', state['events'][-1]['reason'])
            restored = Activity(path)
            self.assertEqual(restored.state, state)
            tracker.ingest([event('4', 'B', trace='other-model', model='claude')], accounts)
            self.assertFalse(state['events'][-1]['switch'])
            tracker.ingest([event('0', 'B', trace='older')], accounts)
            self.assertFalse(state['events'][-1]['switch'])
            self.assertEqual(state['latest']['gemini']['name'], 'a')


if __name__ == '__main__':
    unittest.main()
