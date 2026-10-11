import tempfile
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import yaml
from app import App
from backend import Controller

class ProviderUITests(unittest.TestCase):
    def test_grok_cards_status_active_model_priority_privacy_and_visibility(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory)
            stack.enter_context(patch('app.Controller',lambda:Controller(proxy_dir=root/'proxy',data_dir=root/'data')))
            for method in ('connection_settings','refresh','fetch_quota','fetch_models','start_activity','queue_policy','check_for_updates','refresh_chatgpt_accounts','refresh_claude_accounts','refresh_grok_accounts','refresh_api_live_accounts'):
                stack.enter_context(patch.object(App,method))
            app=App()
            try:
                app.grok_items=[{'name':'grok-one','email':'grok@example.com','provider':'xai','disabled':False,'auth_index':'grok-index','status':'active','quota':{'windows':[]}},
                    {'name':'grok-two','email':'second@example.com','provider':'xai','disabled':False,'status':'error','status_message':'{"error":{"code":"account_suspended","message":"blocked"}}','quota':{'windows':[]}}]
                panel=app.grok_panel;panel.collapsed=False;panel.render();app.update()
                row=panel.rows['grok-one'];card=row['card']
                self.assertFalse(row['windows'])
                self.assertEqual(panel.rows['grok-two']['status'].cget('text').split(' · ')[0],'Account blocked')
                now=datetime.now(timezone.utc).isoformat()
                app.activity_state['latest']={'grok-test':{'name':'grok-one','model':'grok-test','at':now}}
                app.gateway_jobs=[{'model':'grok-test','state':'running'}];app.gateway_jobs_checked=time.monotonic()
                panel.animate();app.update()
                self.assertTrue(row['active_highlight'])
                self.assertTrue(row['model'].cget('text'))
                row['priority'].priority_up.invoke();panel.render();app.update()
                self.assertIs(panel.rows['grok-one']['card'],card)
                footer=app.sidebar_footer.winfo_rooty();panel.toggle();app.update()
                self.assertEqual(app.sidebar_footer.winfo_rooty(),footer)
                self.assertTrue(panel.compact.winfo_viewable())
                app.toggle_account_names();app.update()
                self.assertRegex(row['heading'].cget('text'),r'^Grok [0-9]+$')
                app.service_variables['grok'].set(False);app.set_service_visibility('grok');app.update()
                self.assertFalse(panel.winfo_viewable())
                self.assertFalse(app.pool_summary_groups['grok']['frame'].winfo_viewable())
                self.assertIs(app.sidebar_footer.pack_slaves()[-1],app.tokenharbor_accounts)
            finally:app.closed=True;app.destroy()

    def test_api_cards_keys_stay_hidden_names_and_card_objects_are_retained(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);proxy=root/'proxy';proxy.mkdir()
            config={'server':{'host':'127.0.0.1'},'api-keys':{'openai-compatibility':[{'name':'omni-api-openai-test','base-url':'https://api.openai.com/v1','keys':[{'api-key':'private-dummy-secret'}],'models':[{'name':'gpt-test','alias':'api-openai/gpt-test'}]}]}}
            (proxy/'config.yaml').write_text(yaml.safe_dump(config),encoding='utf-8')
            controller=Controller(proxy_dir=proxy,data_dir=root/'data');controller.preferences['api-account-labels']={'omni-api-openai-test':'Personal API'}
            stack.enter_context(patch('app.Controller',lambda:controller))
            for method in ('connection_settings','refresh','fetch_quota','fetch_models','start_activity','queue_policy','check_for_updates','refresh_chatgpt_accounts','refresh_claude_accounts','refresh_grok_accounts','refresh_api_live_accounts'):
                stack.enter_context(patch.object(App,method))
            app=App()
            try:
                row=app.api_rows['omni-api-openai-test'];card=row['card']
                self.assertEqual(row['heading'].cget('text'),'Personal API')
                self.assertIn('gpt-test',row['models'].cget('text'))
                self.assertNotIn('private-dummy-secret',str(app.api_items))
                app.refresh_api_accounts();self.assertIs(app.api_rows['omni-api-openai-test']['card'],card)
                app.toggle_account_names();self.assertNotIn('Personal',row['heading'].cget('text'))
                app.set_theme('Light');app.set_theme('Dark')
                app.service_variables['openai'].set(False);app.set_service_visibility('openai')
                self.assertNotIn('omni-api-openai-test',app.api_rows)
            finally:app.closed=True;app.destroy()
