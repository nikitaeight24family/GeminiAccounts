import json
import tempfile
import time
import unittest
from unittest.mock import Mock
from backend import Controller, AccountError
from claude_auth import ClaudeAuth
from quota_queue import quota_wait


class ClaudeAuthTests(unittest.TestCase):
    def test_oauth_hosts_and_pool_are_separate(self):
        controller = Mock()
        auth = ClaudeAuth(controller)
        files = [{'name':'google','provider':'antigravity'}, {'name':'gpt','provider':'codex'}, {'name':'claude','provider':'claude'}]
        controller.request.return_value = {'files':files}
        self.assertEqual([a['name'] for a in auth.accounts()], ['claude'])
        controller.request.return_value = {'url':'https://claude.ai/oauth/authorize?state=ok','state':'ok'}
        self.assertEqual(auth.begin_login()[1], 'ok')
        self.assertEqual(controller.request.call_args.args[0], '/anthropic-auth-url?is_webui=true')
        for url in ('http://claude.ai/oauth/authorize','https://claude.ai.evil.test/oauth/authorize','https://claude.ai/other'):
            controller.request.return_value = {'url':url,'state':'ok'}
            with self.assertRaises(AccountError): auth.begin_login()

    def test_usage_plan_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            def request(path, method, payload):
                self.assertEqual(path, '/api-call')
                self.assertEqual(payload['auth_index'], 'index')
                self.assertEqual(payload['header']['Authorization'], 'Bearer $TOKEN$')
                body = {'five_hour':{'utilization':30,'resets_at':'2030-01-01T00:00:00Z'},
                        'seven_day':{'utilization':80,'resets_at':None}} if payload['url'].endswith('usage') else {
                            'organization':{'organization_type':'claude_max','rate_limit_tier':'default_claude_max_5x'}}
                return {'status_code':200,'body':json.dumps(body)}
            controller.request = Mock(side_effect=request)
            auth = ClaudeAuth(controller)
            quota = auth.quota({'name':'claude','auth_index':'index'})
            self.assertEqual([w['remaining'] for w in quota['windows']], [70,20])
            self.assertIsNone(quota['windows'][1]['reset_at'])
            self.assertEqual(quota['plan_type'], 'Max 5x')
            auth.quota({'name':'claude','auth_index':'index'})
            self.assertEqual(controller.request.call_count, 3) # profile is cached
            controller.request.side_effect = None
            controller.request.return_value = {'status_code':403}
            quota = auth.quota({'name':'claude','auth_index':'index'})
            self.assertEqual(quota['windows'], [])
            self.assertEqual(quota['error'], 'Quota HTTP 403')
            self.assertEqual(auth.plan_name({}), 'Plan unknown')
            self.assertEqual(auth.plan_name({'organization':{'rate_limit_tier':'default_claude_max_20x'}}), 'Max 20x')

    def test_rotation_changes_only_claude_and_honors_manual_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            controller.preferences['account-priorities'] = {'later':10}
            now = time.time()
            def account(name,reset):
                return {'name':name,'provider':'claude','disabled':False,'quota':{'windows':[
                    {'label':'5h','remaining':50,'reset_at':now+reset},
                    {'label':'1w','remaining':80,'reset_at':now+600000}]}}
            accounts = [account('soon',1000),account('later',5000)]
            controller.request = Mock(side_effect=lambda path,*args: {'files':accounts+[{'name':'google','provider':'antigravity'}]} if path=='/auth-files' else {'strategy':'fill-first'})
            self.assertTrue(ClaudeAuth(controller).apply_reset_priority(accounts))
            changes = [c.args[2] for c in controller.request.call_args_list if c.args[0]=='/auth-files/fields']
            self.assertEqual([c['name'] for c in changes], ['later','soon'])

    def test_probe_grace_reserve_and_cheap_model(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            controller.models = Mock(return_value=['claude-haiku-4-5','claude-opus-4-6'])
            controller.request = Mock(return_value={'status_code':200,'body':json.dumps({'type':'message','content':[{'type':'text','text':'.'}]})})
            auth = ClaudeAuth(controller)
            account = {'name':'claude','auth_index':'index'}
            quota = {'windows':[{'label':'5h','remaining':100},{'label':'1w','remaining':100}]}
            self.assertIsNone(auth.start_full_quota_window(account,quota,now=1000))
            self.assertIsNone(auth.start_full_quota_window(account,quota,now=1179))
            self.assertEqual(auth.start_full_quota_window(account,quota,now=1180),200)
            request = controller.request.call_args.args[2]
            self.assertEqual(request['url'],'https://api.anthropic.com/v1/messages')
            self.assertEqual(json.loads(request['data'])['model'],'claude-haiku-4-5')
            self.assertIsNone(auth.start_full_quota_window(account,quota,now=1300))
            controller.preferences['quota-floors']={'held':{'claude-native':{'5h':100}}}
            self.assertIsNone(auth.start_full_quota_window(dict(account,name='held'),quota,now=2000))
            self.assertEqual(controller.request.call_count,1)

    def test_queue_can_use_claude_when_google_is_blocked(self):
        blocked = {'name':'google','provider':'antigravity','cooldowns':[{'scope':'credential','reason':'quota','http_status':429,'retry_at':'2030-01-01T00:00:00Z'}]}
        ready = {'name':'claude','provider':'claude','cooldowns':[]}
        self.assertIsNone(quota_wait([blocked,ready],'claude-sonnet-4-6',{},now=1000))
        self.assertIsNotNone(quota_wait([blocked,ready],'gemini-3-pro',{},now=1000))
        ready['cooldowns'] = blocked['cooldowns']
        self.assertIsNotNone(quota_wait([blocked,ready],'claude-sonnet-4-6',{},now=1000))
