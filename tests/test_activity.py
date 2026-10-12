import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activity import Activity


class ActivityTests(unittest.TestCase):
    def test_timer_pings_are_visible_once_without_fabricated_client_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'activity.json'
            tracker = Activity(path)
            accounts = [{'name': 'a', 'auth_index': 'A'}]
            probes = {'a:gemini': {'model': 'gemini-3-flash', 'status': 200, 'attempt_at': 1791758005, 'probe_sent_at': 1791758005},
                      'a:claude': {'model': 'gpt-oss-120b-medium', 'status': 429, 'attempt_at': 1791758006, 'full_since': 1791757000},
                      'unknown:codex': {'model': 'gpt-test', 'status': 200, 'attempt_at': 1791758005},
                      'a:pending': {'model': 'gpt-test', 'status': 'pending', 'attempt_at': 1791758005},
                      'a:unmeasured': {'model': 'gpt-test', 'status': 200},
                      'a:cancelled': {'model': 'gpt-test', 'status': 200, 'attempt_at': 1791758007, 'probe_sent_at': 1791756000},
                      'a:real-usage': {'model': 'gpt-test', 'status': 200, 'attempt_at': 1791758007}}
            state = tracker.ingest_probes(accounts, probes)
            self.assertEqual(len(state['events']), 2)
            self.assertTrue(state['events'][0]['probe'])
            self.assertEqual(state['events'][0]['code'], 200)
            self.assertTrue(state['events'][1]['failed'])
            self.assertEqual(state['stats'], {})
            self.assertEqual(state['latest'], {})
            self.assertEqual(state['model_tokens'], {})
            restored = Activity(path)
            restored.ingest_probes(accounts, probes)
            self.assertEqual(len(restored.state['events']), 2)
            probes['a:gemini']['attempt_at'] += 18000
            probes['a:gemini']['probe_sent_at'] = probes['a:gemini']['attempt_at']
            restored.ingest_probes(accounts, probes)
            self.assertEqual(len(restored.state['events']), 3)

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
            self.assertEqual(state['model_tokens'], {'b': {'gemini': 12}})
            self.assertNotIn('SECRET', path.read_text(encoding='utf-8'))
            tracker.ingest([event('3', 'A', trace='different')], accounts)
            self.assertIn('did not report', state['events'][-1]['reason'])
            restored = Activity(path)
            self.assertEqual(restored.state, state)
            tracker.ingest([event('4', 'B', trace='other-model', model='claude')], accounts)
            self.assertFalse(state['events'][-1]['switch'])
            self.assertEqual(state['model_tokens']['b']['claude'], 12)
            tracker.ingest([event('0', 'B', trace='older')], accounts)
            self.assertFalse(state['events'][-1]['switch'])
            self.assertEqual(state['latest']['gemini']['name'], 'a')

    def test_preserves_actual_upstream_model_while_correlating_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Activity(Path(directory) / 'activity.json')
            state = tracker.ingest([{'execution_id': 'real-model', 'auth_index': 'A',
                'alias': 'claude-haiku-4-5', 'model': 'gemini-3.8-flash-high',
                'timestamp': '2026-10-07T00:00:00Z', 'failed': True}], [{'name': 'a', 'auth_index': 'A'}])
            self.assertEqual(state['stats']['a']['last_model'], 'gemini-3.8-flash-high')
            self.assertEqual(state['events'][0]['upstream_model'], 'gemini-3.8-flash-high')
            self.assertEqual(state['events'][0]['model'], 'claude-haiku-4-5')


if __name__ == '__main__':
    unittest.main()
