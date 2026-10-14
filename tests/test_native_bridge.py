import json
import time
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from backend import Controller, AccountError
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

    def test_restart_shows_encrypted_account_snapshot_before_refresh(self):
        account = {'name':'cached-account','email':'person@example.com','status':'active','access_token':'private-token',
                   'quota':{'plan_type':'free','windows':[{'label':'5h','remaining':73,'reset_at':1800000000}]}}
        self.bridge.publish(account,'openai')
        if self.bridge.cache_timer:
            self.bridge.cache_timer.cancel()
        self.bridge.save_account_cache()
        self.assertNotIn(b'person@example.com',self.bridge.cache_path.read_bytes())
        self.assertNotIn(b'private-token',self.bridge.cache_path.read_bytes())
        restarted = NativeBridge(self.controller,self.messages.append)
        try:
            snapshot = restarted.command({'action':'snapshot'})
            self.assertEqual(len(snapshot['accounts']),1)
            self.assertEqual(snapshot['accounts'][0]['windows'][0]['remaining'],73)
            self.assertNotIn('access_token',snapshot['accounts'][0])
            self.assertEqual(restarted.accounts,{})
            refreshed = {'name':'cached-account','email':'person@example.com','status':'active',
                         'quota':{'observed_at':'2026-10-14T00:00:00Z','signals':[]}}
            restarted.publish(refreshed,'openai')
            self.assertEqual(restarted.command({'action':'snapshot'})['accounts'][0]['windows'][0]['remaining'],73)
            self.assertEqual(restarted.cached_accounts['cached-account']['plan'],'free')
            refreshed['quota']={'windows':[{'label':'5h','remaining':68,'reset_at':1800000000}]}
            restarted.publish(refreshed,'openai')
            self.assertEqual(restarted.command({'action':'snapshot'})['accounts'][0]['windows'][0]['remaining'],73)
            restarted.initial_inventory_complete = True
            self.assertEqual(restarted.command({'action':'snapshot'})['accounts'][0]['windows'][0]['remaining'],68)
        finally:
            if restarted.cache_timer:
                restarted.cache_timer.cancel()
            restarted.pool.shutdown(wait=True,cancel_futures=True)

    def test_parallel_provider_signins_resume_after_bridge_restart(self):
        self.bridge.pending_logins.add('google-state','https://accounts.google.com/signin?state=google-state','gemini')
        self.bridge.pending_logins.add('openai-state','https://auth.openai.com/oauth/authorize?state=openai-state','openai')
        self.bridge.pending_logins.add('claude-state','https://claude.ai/oauth/authorize?state=claude-state','claude')
        self.bridge.pending_logins.add('grok-state','https://accounts.x.ai/oauth?state=grok-state','grok')
        restarted = NativeBridge(self.controller,self.messages.append)
        try:
            from unittest.mock import Mock
            self.controller.login_status = Mock(return_value={'status':'wait'})
            restarted.clients['openai'].login_status = Mock(return_value={'status':'wait'})
            restarted.clients['claude'].login_status = Mock(return_value={'status':'ok'})
            restarted.clients['grok'].login_status = Mock(return_value={'status':'wait'})
            self.assertEqual(restarted.command({'action':'login_status','provider':'gemini','state':'google-state'})['status'],'wait')
            self.assertEqual(restarted.command({'action':'login_status','provider':'openai','state':'openai-state'})['status'],'wait')
            self.assertEqual(restarted.command({'action':'login_status','provider':'claude','state':'claude-state'})['status'],'ok')
            self.assertEqual(restarted.command({'action':'login_status','provider':'grok','state':'grok-state'})['status'],'wait')
            self.controller.login_status.assert_called_once_with('google-state')
            restarted.clients['openai'].login_status.assert_called_once_with('openai-state')
            restarted.clients['claude'].login_status.assert_called_once_with('claude-state')
            restarted.clients['grok'].login_status.assert_called_once_with('grok-state')
            self.assertIsNotNone(restarted.pending_logins.get('google-state'))
            self.assertIsNotNone(restarted.pending_logins.get('openai-state'))
            self.assertIsNone(restarted.pending_logins.get('claude-state'))
            self.assertIsNotNone(restarted.pending_logins.get('grok-state'))
            self.assertEqual(restarted.command({'action':'login_status','provider':'claude','state':'claude-state'})['status'],'ok')
            with self.assertRaises(AccountError):
                restarted.command({'action':'login_status','provider':'openai','state':'google-state'})
            with self.assertRaises(AccountError):
                restarted.command({'action':'login_cancel','provider':'claude','state':'google-state'})
            self.assertIsNotNone(restarted.pending_logins.get('google-state'))
        finally:
            restarted.pool.shutdown(wait=True,cancel_futures=True)

    def test_completed_login_checks_credential_and_flags_same_identity(self):
        started = time.time() - 2
        created = datetime.now(timezone.utc).isoformat()
        fresh = {'name':'new','provider':'codex','email':'same@example.test','auth_index':'new-index',
                 'created_at':created,'status':'active','failed':0}
        old = {'name':'old','provider':'codex','email':'same@example.test','auth_index':'old-index',
               'created_at':'2020-01-01T00:00:00Z','status':'active'}
        self.controller.request = Mock(return_value={'files':[old,fresh]})
        self.bridge.clients['openai'].quota = Mock(return_value={'windows':[]})
        result = self.bridge.review_login('openai',started)
        self.assertEqual(result,{'status':'verified','duplicate':True})
        self.bridge.clients['openai'].quota.assert_called_once_with(fresh)
        self.bridge.clients['openai'].quota = Mock(return_value={'error':'Quota HTTP 401'})
        self.assertEqual(self.bridge.review_login('openai',started)['status'],'error')

    def test_parallel_same_provider_login_review_does_not_guess_account(self):
        created = datetime.now(timezone.utc).isoformat()
        rows=[{'name':str(n),'provider':'codex','created_at':created,'auth_index':str(n)} for n in (1,2)]
        self.controller.request = Mock(return_value={'files':rows})
        self.assertEqual(self.bridge.review_login('openai',time.time()-2),{'status':'uncertain'})

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

    def test_google_missing_summary_is_not_reported_available(self):
        account = {'name':'google','status':'active','quota':{'groups':[], 'summary_error':'Summary unavailable'}}
        dto = self.bridge.account_dto(account,'gemini')
        self.assertEqual(dto['status'],'Quota unavailable')
        self.assertEqual(dto['severity'],'warning')
        self.assertEqual(dto['windows'],[])

    def test_failed_quota_retains_last_values_and_marks_them_unavailable(self):
        account = {'name':'google','status':'active','quota':{'groups':[{'kind':'gemini','buckets':[{'window':'5h','remaining':.7}]}]}}
        self.bridge.accounts['google']=(account,'gemini')
        self.controller.quotas=Mock(side_effect=RuntimeError('network unavailable'))
        self.bridge.fetch_quota(account,'gemini')
        dto=self.messages[-1]['account']
        self.assertEqual(dto['status'],'Quota unavailable')
        self.assertEqual(dto['windows'][0]['remaining'],70)
        self.controller.quotas=Mock(return_value={'groups':[{'kind':'gemini','buckets':[{'window':'5h','remaining':.9}]}]})
        self.bridge.fetch_quota(account,'gemini')
        self.assertEqual(self.messages[-1]['account']['status'],'Available')
        self.assertEqual(self.messages[-1]['account']['windows'][0]['remaining'],90)

    def test_quota_refresh_runs_bounded_automatic_hello_probe(self):
        account = {'name':'google','status':'active'}
        self.bridge.accounts['google']=(account,'gemini')
        quota = {'groups':[{'kind':'gemini','buckets':[{'window':'5h','remaining':1},{'window':'weekly','remaining':1}]}]}
        self.controller.quotas=Mock(return_value=quota)
        self.controller.start_full_quota_windows=Mock(return_value=[])
        self.bridge.fetch_quota(account,'gemini')
        self.controller.start_full_quota_windows.assert_called_once_with(account,quota,last_used={})

    def test_quota_refresh_runs_provider_hello_probe_for_claude_and_openai(self):
        for provider in ('claude','openai'):
            account={'name':provider,'status':'active'}
            self.bridge.accounts[provider]=(account,provider)
            client=self.bridge.clients[provider]
            client.quota=Mock(return_value={'windows':[]})
            client.start_full_quota_window=Mock(return_value=None)
            self.bridge.fetch_quota(account,provider)
            client.start_full_quota_window.assert_called_once_with(account,{'windows':[]})

    def test_old_quota_response_cannot_restore_removed_or_replaced_account(self):
        old={'name':'google','status':'active'}
        new={'name':'google','status':'active','disabled':True}
        self.bridge.accounts['google']=(new,'gemini')
        self.controller.quotas=Mock(return_value={'groups':[]})
        self.bridge.fetch_quota(old,'gemini')
        self.assertIs(self.bridge.accounts['google'][0],new)
        self.assertEqual(self.messages,[])
        self.controller.quotas=Mock(side_effect=RuntimeError('network'))
        self.bridge.fetch_quota(old,'gemini')
        self.assertEqual(self.messages,[])

    def test_quota_loading_does_not_hide_paused_or_blocked_status(self):
        for fields, expected in [({},'Loading quota'),({'disabled':True},'Paused'),({'access_issue':'login'},'Sign in again')]:
            dto=self.bridge.account_dto({'name':'google','status':'active',**fields},'gemini')
            self.assertEqual(dto['status'],expected)

    def test_api_add_uses_service_names_for_every_provider(self):
        self.bridge.api.add=Mock()
        self.bridge.pool.submit=Mock()
        for provider,service in [('gemini','Gemini'),('openai','OpenAI'),('claude','Claude'),('grok','Grok'),('tokenharbor','TokenHarbor')]:
            self.bridge.command({'action':'api','provider':provider,'key':'test','label':'Work'})
            self.bridge.api.add.assert_called_with(service,'test','Work')

    def test_tokenharbor_has_its_own_connection_flow(self):
        self.bridge.harbor.connect=Mock()
        self.bridge.pool.submit=Mock()
        self.bridge.command({'action':'harbor_connect','key':'test'})
        self.bridge.harbor.connect.assert_called_once_with('test')
        with self.assertRaisesRegex(Exception,'API key'):
            self.bridge.command({'action':'login','provider':'tokenharbor'})

    def test_cancelling_claude_does_not_cancel_openai(self):
        self.bridge.clients['claude'].cancel_login=Mock()
        self.bridge.clients['openai'].cancel_login=Mock()
        self.bridge.pending_logins.add('example','https://claude.ai/oauth','claude')
        self.bridge.command({'action':'login_cancel','provider':'claude','state':'example'})
        self.bridge.clients['claude'].cancel_login.assert_called_once_with('example')
        self.bridge.clients['openai'].cancel_login.assert_not_called()

    def test_expired_quota_schedules_one_refresh_per_account(self):
        self.bridge.pool.submit=Mock()
        account={'name':'openai','quota':{'windows':[{'reset_at':100},{'reset_at':101}]}}
        self.bridge.accounts['openai']=(account,'openai')
        self.bridge.refresh_expired_quotas(now=200)
        self.bridge.refresh_expired_quotas(now=200)
        self.bridge.pool.submit.assert_called_once()
        self.assertNotIn('remaining',account['quota']['windows'][0])

    def test_quota_window_ordering_and_family_grouping(self):
        gemini_account = {
            'name': 'gemini_test',
            'quota': {
                'groups': [
                    {'kind': 'claude', 'buckets': [{'window': 'weekly', 'remaining': 0.4}, {'window': '5h', 'remaining': 0.7}]},
                    {'kind': 'gemini', 'buckets': [{'window': 'weekly', 'remaining': 0.5}, {'window': '5h', 'remaining': 0.9}]}
                ]
            }
        }
        dto = self.bridge.account_dto(gemini_account, 'gemini')
        self.assertEqual([w['id'] for w in dto['windows']],
                         ['gemini/5h', 'gemini/weekly', 'claude/5h', 'claude/weekly'])
        self.assertEqual([w['label'] for w in dto['windows']], ['5h', '1w', '5h', '1w'])
        self.assertEqual([w['family'] for w in dto['windows']], ['gemini', 'gemini', 'claude', 'claude'])

        openai_account = {
            'name': 'openai_test',
            'quota': {
                'windows': [
                    {'label': '1mo', 'remaining': None},
                    {'label': '1w', 'remaining': 80},
                    {'label': '5h', 'remaining': 60}
                ]
            }
        }
        dto = self.bridge.account_dto(openai_account, 'openai')
        self.assertEqual([w['label'] for w in dto['windows']], ['5h', '1w', '1mo'])
        self.assertIsNone(dto['windows'][2]['remaining'])
        self.assertEqual(dto['windows'][0]['remaining'], 60)

    def test_active_openai_token_refresh_is_not_shown_as_signed_out(self):
        account = {'name': 'openai_refreshing', 'status': 'active',
                   'status_message': '{"error":{"code":401,"type":"authentication_error"}}',
                   'quota': {'windows': []}}
        dto = self.bridge.account_dto(account, 'openai')
        self.assertEqual(dto['status'], 'Checking sign-in')
        self.assertEqual(dto['severity'], 'warning')

    def test_revoked_openai_token_is_shown_as_sign_in_again(self):
        account = {'name': 'openai_revoked', 'status': 'active',
                   'quota': {'error': 'Quota HTTP 401: token_revoked'}}
        dto = self.bridge.account_dto(account, 'openai')
        self.assertEqual(dto['status'], 'Sign in again')
        self.assertEqual(dto['severity'], 'error')


    def test_future_and_disabled_quotas_do_not_trigger_refresh(self):
        self.bridge.pool.submit=Mock()
        self.bridge.accounts={'a':({'name':'a','quota':{'windows':[{'reset_at':300}]}},'openai'),
                              'b':({'name':'b','disabled':True,'quota':{'windows':[{'reset_at':100}]}},'openai')}
        self.bridge.refresh_expired_quotas(now=200)
        self.bridge.pool.submit.assert_not_called()

    def test_quota_refresh_has_cooldown_after_completion(self):
        self.bridge.pool.submit=Mock()
        account={'name':'a'}
        self.assertTrue(self.bridge.schedule_quota(account,'openai',now=100))
        self.bridge.quota_pending.clear()
        self.assertFalse(self.bridge.schedule_quota(account,'openai',now=110))
        self.assertTrue(self.bridge.schedule_quota(account,'openai',now=131))

    def test_recent_activity_publishes_model_and_expires(self):
        account={'name':'one','status':'active','success':3}
        self.bridge.accounts['one']=(account,'openai')
        self.controller.request=Mock(side_effect=lambda path: {'files':[]} if path=='/auth-files' else [])
        self.controller.model_aliases=Mock(return_value={})
        self.bridge.activity.ingest=Mock()
        self.bridge.activity.state['latest']={'gpt-test':{'name':'one','at':'2026-01-01T00:00:00+00:00','model':'gpt-test'}}
        from datetime import datetime
        now=datetime.fromisoformat('2026-01-01T00:00:02+00:00').timestamp()
        self.bridge.poll_activity(now)
        dto=self.messages[-1]['account']
        self.assertTrue(dto['active']);self.assertEqual(dto['model'],'gpt-test');self.assertEqual(dto['activity'],'recent')
        self.bridge.poll_activity(now+61)
        self.assertFalse(self.messages[-1]['account']['active'])
        self.assertEqual(self.messages[-1]['account']['model'],'')

    def test_running_job_immediately_activates_account_and_displays_model(self):
        account = {'name': 'one', 'status': 'active', 'auth_index': 'idx-1'}
        self.bridge.accounts['one'] = (account, 'openai')
        self.controller.request = Mock(side_effect=lambda path: {'files': [{'name': 'one', 'auth_index': 'idx-1'}]} if path == '/auth-files' else [])
        self.controller.model_aliases = Mock(return_value={})
        self.controller.quota_wait_status = Mock(return_value={'jobs': [{'state': 'running', 'model': 'gpt-6.1-sol', 'auth_index': 'idx-1'}]})
        self.bridge.activity.ingest = Mock()
        self.bridge.poll_activity(100)
        dto = self.messages[-1]['account']
        self.assertTrue(dto['active'])
        self.assertEqual(dto['model'], 'gpt-6.1-sol')
        self.assertEqual(dto['activity'], 'running')
