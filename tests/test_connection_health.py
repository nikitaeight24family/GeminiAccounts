import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import tomllib
from backend import Controller
from integrations import Integrations
from connection_health import ConnectionHealth,CLIENTS

class ConnectionHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.c=Controller(proxy_dir=root/'proxy',data_dir=root/'data');self.c.proxy_dir.mkdir()
        (self.c.proxy_dir/'client-key.txt').write_text('local-test-key')
        (self.c.proxy_dir/'cliproxy-models.json').write_text(json.dumps({'antigravity':[{'id':'gemini-3-flash'},{'id':'gemini-pro-agent'}]}))
        self.c.preferences.update({'gemini-model':'gemini-3-flash','claude-model':'claude-sonnet-4-6'})
        self.c.family_model_choices=Mock(return_value={'gemini':['gemini-3-flash'],'claude':['claude-sonnet-4-6']})
        self.c.chatgpt_model_choices=Mock(return_value=[]);self.c.accounts=Mock(return_value=[])
        self.routes=[]
        def request(path,method='GET',payload=None):
            if path=='/oauth-model-alias':
                if method=='PATCH':self.routes=payload['aliases']
                return {'oauth-model-alias':{'antigravity':self.routes}}
            raise ValueError('Unexpected request')
        self.c.request=request;self.c.model_aliases=lambda:{r['alias']:r['name'] for r in self.routes}
        self.i=Integrations(self.c,root/'home',root/'local');self.h=ConnectionHealth(self.i)
        self.i.connection_models=lambda: {'gemini-3-flash','claude-sonnet-4-6'}
        self.h.probe=lambda:{'key':'local-test-key','models':{'gemini-3-flash','gemini-selected','claude-sonnet-4-5','claude-selected','claude-sonnet-4-6','claude-opus-4-6-thinking',*(r['alias'] for r in self.routes)}}
    def tearDown(self):self.tmp.cleanup()
    def row(self,client):return next(r for r in self.h.maintain() if r['id']==client)
    def test_never_connects_new_apps_automatically(self):
        self.assertTrue(all(not r['connected'] for r in self.h.maintain()))
        self.assertFalse(any(p.exists() for paths in self.i.paths().values() for p in paths))
    def test_each_app_connects_and_reconnects_without_duplicate_routes(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.h.connect(client);self.h.connect(client)
                self.assertEqual(self.row(client)['status'],'configured')
                self.assertEqual(len(self.routes),len({r['alias'] for r in self.routes}))
    def test_transport_repair_preserves_models_and_user_settings_for_each_app(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.h.connect(client);path,doc=self.h.read(client);before_models=self.h.models(client,doc)
                if client=='codex':
                    path.write_text(path.read_text().replace('http://127.0.0.1:8317/v1','http://127.0.0.1:9999/v1')+'\n[features]\ncustom_user_flag = true\n')
                else:
                    doc['user_setting']='keep';actual,_=self.h.expected(client,doc,'local-test-key')
                    actual['ANTHROPIC_BASE_URL' if client=='claude_cli' else 'inferenceGatewayBaseUrl']='http://127.0.0.1:9999'
                    self.i.write_json(path,doc)
                row=self.row(client);self.assertEqual(row['status'],'configured');self.assertTrue(row['repaired'])
                _,doc=self.h.read(client);self.assertEqual(self.h.models(client,doc),before_models)
                self.assertEqual(doc['features']['custom_user_flag'] if client=='codex' else doc['user_setting'],True if client=='codex' else 'keep')
    def test_unavailable_model_is_not_silently_replaced(self):
        self.h.connect('claude_desktop');path,doc=self.h.read('claude_desktop')
        doc['inferenceModels'].append({'name':'claude-sonnet-4-5-ga-pro-agent'})
        self.i.write_json(path,doc);before=path.read_bytes();row=self.row('claude_desktop')
        self.assertIn('claude-sonnet-4-5-ga-pro-agent',row['unavailableModels']);self.assertEqual(before,path.read_bytes())
        self.assertFalse(any(r['name']=='gemini-pro-agent' for r in self.routes))

    def test_gateway_login_regression_is_repaired_without_touching_identity(self):
        self.h.connect('codex')
        path, _ = self.h.read('codex')
        identity = path.parent / 'auth.json'
        identity.write_bytes(b'{"unrelated_identity":"preserve"}')
        path.write_text(path.read_text().replace('requires_openai_auth = false', 'requires_openai_auth = true'))
        row = self.row('codex')
        self.assertEqual(row['status'], 'configured')
        self.assertFalse(tomllib.loads(path.read_text())['model_providers']['gemini_accounts']['requires_openai_auth'])
        self.assertEqual(identity.read_bytes(), b'{"unrelated_identity":"preserve"}')
    def test_missing_route_is_restored_only_for_live_target(self):
        self.h.connect('claude_desktop');self.routes=[]
        row=self.row('claude_desktop');self.assertEqual(row['status'],'configured');self.assertTrue(row['repaired'])
    def test_each_app_reports_gateway_outage_auth_and_busy_without_mutation(self):
        for client in CLIENTS:self.h.connect(client)
        before={p:p.read_bytes() for paths in self.i.paths().values() for p in paths if p.exists()}
        for error in ('gateway_unavailable','gateway_auth','gateway_busy'):
            self.h.probe=lambda error=error:{'error':error}
            self.assertTrue(all(r['status']==error for r in self.h.maintain()))
        self.assertEqual(before,{p:p.read_bytes() for p in before})
    def test_restart_always_needs_explicit_consent(self):
        self.h.connect('codex');self.i.restart_desktop=Mock()
        for consent in (False,None,'true',1):
            with self.assertRaises(Exception):self.h.restart('codex',consent)
        self.i.restart_desktop.assert_not_called();self.h.restart('codex',True);self.i.restart_desktop.assert_called_once_with(['codex'])
    def test_failed_repair_restores_exact_bytes_and_backs_off(self):
        self.h.connect('claude_cli');path,doc=self.h.read('claude_cli');doc['env']['ANTHROPIC_BASE_URL']='broken';self.i.write_json(path,doc);before=path.read_bytes()
        def fail(*args):path.write_text('{}');raise RuntimeError('failed')
        with patch.object(self.h,'repair_config',side_effect=fail) as repair:
            self.assertEqual(self.row('claude_cli')['status'],'check_failed');self.row('claude_cli');self.assertEqual(repair.call_count,1)
        self.assertEqual(path.read_bytes(),before)

    def test_started_process_does_not_claim_session_recovery(self):
        self.h.connect('codex')
        self.i.restart_desktop = Mock()
        result = self.h.restart('codex', True)
        self.assertFalse(result['sessionVerified'])
        self.assertTrue(self.h.state['restart']['codex'])

    def test_catalog_sync_runs_automatically_for_connected_desktop(self):
        self.h.connect('claude_desktop')
        original = self.c.request
        def request(path, method='GET', payload=None):
            if path == '/auth-files': return {'files': [{'name': 'account', 'provider': 'antigravity'}]}
            if path.startswith('/auth-files/models?'): return {'models': [{'id': 'gemini-new'}]}
            return original(path, method, payload)
        self.c.request = request
        self.h.probe = lambda: {'key':'local-test-key', 'models':{'gemini-new', *(r['alias'] for r in self.routes)}}
        self.h.catalog_after = 0
        row = self.row('claude_desktop')
        _, doc = self.h.read('claude_desktop')
        self.assertEqual([m['name'] for m in doc['inferenceModels']], [self.i.claude_desktop_route('gemini-new')])
        self.assertTrue(row['restartRequired'])
        self.assertNotIn('model_unavailable', row['issues'])
        self.assertTrue(self.h.state['beforeCatalogSync'])
