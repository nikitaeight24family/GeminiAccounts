import json
import tempfile
import unittest
from pathlib import Path
from provider_errors import failure_reason
from activity import Activity


class ProviderErrorsTests(unittest.TestCase):
    def test_google_error_classification(self):
        for reason, expected in [('RATE_LIMIT_EXCEEDED', 'request rate'), ('MODEL_CAPACITY_EXHAUSTED', 'capacity'), ('QUOTA_EXHAUSTED', 'quota exhausted')]:
            body = json.dumps({'error': {'code': 429, 'details': [{'reason': reason}]}})
            self.assertIn(expected, failure_reason(429, body))
        self.assertIn('exact cause unavailable', failure_reason(429, 'not json'))
        self.assertIn('exact cause unavailable', failure_reason(429, {'error': {'details': None}}))
        self.assertIsNone(failure_reason(403, {}))

    def test_activity_keeps_classification_without_raw_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'activity.json'
            tracker = Activity(path)
            state = tracker.ingest([{'execution_id': 'one', 'auth_index': 'a', 'failed': True,
                'fail': {'status_code': 429, 'body': json.dumps({'error': {'message': 'Model capacity unavailable SECRET_KEY https://secret', 'code': 429}})}}],
                [{'name': 'account', 'auth_index': 'a'}])
            self.assertIn('capacity unavailable', state['events'][0]['reason'])
            self.assertNotIn('SECRET', path.read_text())
            self.assertNotIn('https://secret', path.read_text())

    def test_nested_native_error_preserves_google_reason(self):
        google = {'error':{'code':429, 'status':'RESOURCE_EXHAUSTED', 'details':[{'reason':'MODEL_CAPACITY_EXHAUSTED'}]}}
        wrapped = {'type':'error','error':{'type':'rate_limit_error','message':json.dumps(google)}}
        self.assertIn('capacity unavailable', failure_reason(429, json.dumps(wrapped)))
