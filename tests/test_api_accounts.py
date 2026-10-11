import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import yaml
from api_accounts import APIAccounts, SERVICES, NoRedirect
from grok_auth import GrokAuth
from backend import AccountError, Controller


class APIAccountTests(unittest.TestCase):
    def test_all_services_catalogs_headers_and_no_paid_generation(self):
        for service in SERVICES:
            with self.subTest(service=service):
                body = {'models':[{'name':'models/gemini-test','supportedGenerationMethods':['generateContent']},
                                 {'name':'models/embedding','supportedGenerationMethods':['embedContent']}]} if service=='Gemini' else {
                                     'data':[{'id':'gpt-test' if service=='OpenAI' else 'chat-test'}]}
                response = io.StringIO(json.dumps(body))
                response.__enter__ = lambda: response
                opener = MagicMock()
                opener.open.return_value.__enter__.return_value = response
                with patch('api_accounts.urllib.request.build_opener',return_value=opener):
                    models=APIAccounts.discover(service,'dummy-test-key')
                self.assertEqual(len(models),1)
                request=opener.open.call_args.args[0]
                self.assertEqual(request.get_method(),'GET')
                self.assertNotIn('dummy-test-key',request.full_url)
                if service=='Gemini':self.assertEqual(request.get_header('X-goog-api-key'),'dummy-test-key')
                elif service=='Claude':self.assertEqual(request.get_header('X-api-key'),'dummy-test-key')
                else:self.assertEqual(request.get_header('Authorization'),'Bearer dummy-test-key')

    def test_managed_groups_preserve_other_keys_isolate_models_and_priorities(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=Controller(proxy_dir=root,data_dir=root/'data')
            original={'server':{'host':'127.0.0.1'},'api-keys':{'claude':[{'name':'unrelated','keys':[{'api-key':'other-dummy'}]}]}}
            (root/'config.yaml').write_text(yaml.safe_dump(original),encoding='utf-8')
            manager=APIAccounts(controller)
            models=[{'name':'chat-test','alias':'chat-test','display-name':'Chat'}]
            with patch.object(manager,'discover',return_value=models),patch.object(manager,'live_index',return_value='registered'):
                for service in SERVICES:
                    name=manager.add(service,'dummy-'+service,service+' personal')
                    manager.change(name,2)
                    manager.add(service,'dummy-'+service,service+' personal')
            accounts=manager.accounts()
            self.assertEqual(len(accounts),5)
            self.assertTrue(all(a['priority']==2 for a in accounts))
            current=yaml.safe_load((root/'config.yaml').read_text())
            self.assertEqual(current['api-keys']['claude'][0],original['api-keys']['claude'][0])
            for groups in current['api-keys'].values():
                for group in groups:
                    if group['name']=='unrelated':continue
                    self.assertNotIn('prefix',group)
                    self.assertTrue(all(m['alias'].startswith('api-') for m in group['models']))
            preferences=json.dumps(controller.preferences)
            self.assertNotIn('dummy-',preferences)
            manager.remove(accounts[0]['name'])
            self.assertEqual(len(manager.accounts()),4)
            with self.assertRaises(AccountError):manager.remove('unrelated')

    def test_gateway_registration_failure_restores_exact_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);controller=Controller(proxy_dir=root,data_dir=root/'data')
            previous=b'server: {host: 127.0.0.1}\n# user comment\n'
            (root/'config.yaml').write_bytes(previous)
            manager=APIAccounts(controller)
            with patch.object(manager,'discover',return_value=[{'name':'gpt-test'}]),patch.object(manager,'live_index',return_value=None),patch('api_accounts.time.sleep'):
                with self.assertRaises(AccountError):manager.add('OpenAI','dummy-key')
            self.assertEqual((root/'config.yaml').read_bytes(),previous)
            self.assertNotIn('api-account-labels',controller.preferences)

    def test_redirects_cannot_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))


class GrokAuthTests(unittest.TestCase):
    def test_device_flow_safe_hosts_and_independent_oauth_accounts(self):
        controller=Mock();auth=GrokAuth(controller)
        controller.request.return_value={'url':'https://accounts.x.ai/oauth2/device?user_code=123','state':'session','user_code':'123'}
        result=auth.begin_login()
        self.assertEqual(result['user_code'],'123')
        self.assertEqual(controller.request.call_args.args[0],'/xai-auth-url?is_webui=true')
        for url in ('http://accounts.x.ai/device','https://accounts.x.ai.evil.example/device','https://grok.com/other'):
            controller.request.return_value={'url':url,'state':'session'}
            with self.assertRaises(AccountError):auth.begin_login()
        controller.request.return_value={'files':[{'name':'oauth','provider':'xai','source':'file'},
            {'name':'api','provider':'xai','runtime_only':True}, {'name':'google','provider':'antigravity'}]}
        self.assertEqual([a['name'] for a in auth.accounts()],['oauth'])
        self.assertEqual(auth.quota({})['windows'],[])
        self.assertIsNone(auth.start_full_quota_window({},{}))
