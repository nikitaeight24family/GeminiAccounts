import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from backend import Controller
from native_bridge import NativeBridge


class NativeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.controller = Controller(proxy_dir=root/'proxy', data_dir=root/'data')
        self.messages = []
        self.bridge = NativeBridge(self.controller,self.messages.append)

    def tearDown(self):
        self.bridge.pool.shutdown(wait=True,cancel_futures=True)
        self.directory.cleanup()

    def test_settings_hide_exact_service_without_hiding_google_claude_quota(self):
        for provider in ('claude','grok'):
            self.bridge.command({'action':'visibility','provider':provider,'value':False})
        prefs = self.bridge.preferences()
        self.assertTrue(prefs['visible']['gemini'])
        self.assertFalse(prefs['visible']['claude'])
        self.assertFalse(prefs['visible']['grok'])
        account = {'name':'google','quota':{'groups':[{'kind':'claude','buckets':[{'window':'weekly','remaining':.4}]}]}}
        dto = self.bridge.account_dto(account,'gemini')
        self.assertEqual(dto['windows'][0]['remaining'],40)
        self.assertEqual(dto['windows'][0]['id'],'claude/weekly')

    def test_sanitized_dto_never_exposes_credentials(self):
        account = {'name':'gpt','email':'demo@example.com','access_token':'secret-token','refresh_token':'secret-refresh',
                   'api_key':'secret-key','quota':{'plan_type':'plus','windows':[{'label':'1w','remaining':72}]}}
        dto = self.bridge.account_dto(account,'openai')
        encoded = json.dumps(dto)
        self.assertNotIn('secret',encoded)
        self.assertEqual(dto['windows'][0]['id'],'openai/weekly')
        self.assertEqual(dto['plan'],'plus')

    def test_pause_and_resume_do_not_delete_account(self):
        self.controller._set_disabled = Mock()
        self.bridge.pool.submit = Mock()
        account = {'name':'google','disabled':False}
        self.bridge.accounts['google'] = (account,'gemini')
        self.bridge.command({'action':'pause','id':'google'})
        self.controller._set_disabled.assert_called_once_with(account,True)
        self.assertIn('google',self.bridge.accounts)
        account['disabled'] = True
        self.bridge.command({'action':'pause','id':'google'})
        self.controller._set_disabled.assert_called_with(account,False)

    def test_rename_while_private_preserves_privacy_and_credentials(self):
        self.controller.preferences['hide-account-names'] = True
        account = {'name':'one','email':'private@example.com','refresh_token':'unchanged'}
        self.bridge.accounts['one'] = (account,'openai')
        self.bridge.command({'action':'rename','id':'one','label':'Work'})
        self.assertTrue(self.bridge.preferences()['private'])
        self.assertEqual(self.bridge.account_dto(account,'openai')['label'],'Work')
        self.assertEqual(account['refresh_token'],'unchanged')

    def test_no_desktop_toolkit_dependency_in_headless_backend(self):
        import subprocess, sys
        result = subprocess.run([sys.executable,'-c',
                                 "import native_bridge,sys; assert 'tkinter' not in sys.modules; assert 'customtkinter' not in sys.modules"],
                                capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def test_tokenharbor_pause_preserves_keys_and_other_configuration(self):
        import yaml
        from tokenharbor import TokenHarbor, PROVIDER
        from integrations import Integrations
        self.controller.proxy_dir.mkdir()
        path = self.controller.proxy_dir/'config.yaml'
        path.write_text(yaml.safe_dump({'api-keys':{'claude':[TokenHarbor.group(['dummy-a','dummy-b'])]},
                                       'unrelated':{'preserve':True}}),encoding='utf-8')
        client = TokenHarbor(self.controller,Integrations(self.controller))
        client.set_key_paused('dummy-a',True)
        self.assertEqual(set(client.keys()),{'dummy-a','dummy-b'})
        self.assertEqual(client.paused_keys(),['dummy-a'])
        client.set_key_paused('dummy-b',True)
        config = yaml.safe_load(path.read_text('utf-8'))
        self.assertFalse(any(group['name']==PROVIDER for group in config['api-keys']['claude']))
        self.assertTrue(config['unrelated']['preserve'])
        client.set_key_paused('dummy-a',False)
        self.assertEqual(client.paused_keys(),['dummy-b'])
        config = yaml.safe_load(path.read_text('utf-8'))
        self.assertEqual(config['api-keys']['claude'][0]['keys'],[{'api-key':'dummy-a'}])
