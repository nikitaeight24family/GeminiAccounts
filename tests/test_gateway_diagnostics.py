import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from gateway_diagnostics import Diagnostics, export_diagnostics
from activity import Activity
from provider_errors import provider_error_metadata, failure_reason


class DiagnosticsTests(unittest.TestCase):
    def test_rotation_and_disallowed_payload_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gateway-diagnostics.jsonl'
            log = Diagnostics(path, max_bytes=1)
            log.record('request', 'started', model='gemini', authorization='SECRET', body='PRIVATE')
            log.record('request', 'finished', status=200)
            self.assertTrue(path.with_suffix('.previous.jsonl').exists())
            content = path.read_text() + path.with_suffix('.previous.jsonl').read_text()
            self.assertNotIn('SECRET', content)
            self.assertNotIn('PRIVATE', content)
            self.assertFalse(log.write_error)

    def test_export_contains_live_jobs_and_files_without_config_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'gateway-diagnostics.jsonl').write_text('{"event":"received"}\n')
            (root / 'config.yaml').write_text('SECRET')
            controller = SimpleNamespace(data_dir=root,
                quota_wait_status=lambda: {'jobs':[{'model':'opus','state':'waiting'}]},
                accounts=lambda: [{'name':'a','disabled':False,'api_key':'SECRET','verification_url':'SECRET'}])
            result = export_diagnostics(controller, root / 'export.zip')
            with zipfile.ZipFile(result) as archive:
                self.assertNotIn('config.yaml', archive.namelist())
                snapshot = json.loads(archive.read('snapshot.json'))
                self.assertEqual(snapshot['jobs']['jobs'][0]['model'], 'opus')
                self.assertNotIn('SECRET', archive.read('snapshot.json').decode())
                self.assertIn('gateway-diagnostics.jsonl', archive.namelist())

    def test_failed_failover_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Activity(Path(directory) / 'activity.json')
            records = [{'execution_id': str(i), 'trace_id':'same', 'auth_index': name,
                'model':'claude-opus', 'failed':True, 'fail':{'status_code':429},
                'timestamp':f'2026-10-08T00:00:0{i}Z'} for i, name in [(1,'a'),(2,'b')]]
            state = tracker.ingest(records, [{'name':'a','auth_index':'a'},{'name':'b','auth_index':'b'}])
            self.assertTrue(state['events'][1]['switch'])
            self.assertEqual(state['events'][1]['from'], 'a')
            self.assertTrue((Path(directory) / 'provider-diagnostics.jsonl').exists())

    def test_generic_quota_message_does_not_claim_full_exhaustion(self):
        body = {'error':{'status':'RESOURCE_EXHAUSTED','message':'Quota exceeded SECRET',
            'details':[{'reason':'RATE_LIMIT_EXCEEDED','retryDelay':'3s','metadata':{'key':'SECRET'}}]}}
        self.assertNotIn('quota exhausted', failure_reason(429, {'error':{'message':'Quota exceeded'}}))
        metadata = provider_error_metadata(body)
        self.assertEqual(metadata['retry_delay'], '3s')
        self.assertNotIn('SECRET', json.dumps(metadata))
