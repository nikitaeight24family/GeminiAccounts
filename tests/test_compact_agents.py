import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app import App
from backend import Controller


class CompactAgentsTests(unittest.TestCase):
    def test_hidden_ui_separate_quotas_rest_stop_and_telegram_settings(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch('app.Controller', lambda: Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')))
            for method in ('refresh', 'fetch_quota', 'fetch_models', 'start_activity', 'queue_policy',
                           'check_for_updates', 'poll_gateway_jobs', 'refresh_chatgpt_accounts',
                           'refresh_claude_accounts', 'refresh_grok_accounts', 'refresh_api_live_accounts',
                           'show_saved_window'):
                stack.enter_context(patch.object(App, method))
            app = App()
            app.withdraw()
            errors = []
            app.report_callback_exception = lambda *args: errors.append(args)
            try:
                app.chatgpt_items = [
                    {'name': 'paid', 'plan_type': 'plus', 'status': 'active', 'quota': {'windows': [
                        {'label': '5h', 'remaining': 80}, {'label': '1w', 'remaining': 90}]}},
                    {'name': 'free', 'plan_type': 'free', 'status': 'active', 'quota': {'windows': [
                        {'label': '5h', 'remaining': 30}, {'label': '1w', 'remaining': 40}]}},
                    {'name': 'empty', 'plan_type': 'plus', 'quota': {'windows': [
                        {'label': '5h', 'remaining': 100}, {'label': '1w', 'remaining': 0}]}}]
                app.draw_chatgpt_accounts()
                self.assertEqual(app.chatgpt_compact.dot_values, (.9, .45))
                self.assertEqual(app.chatgpt_free_compact.dot_values, (.3, .4))
                app.chatgpt_collapsed = False
                app.draw_chatgpt_accounts()
                self.assertEqual(app._chatgpt_order[1][-1], 'empty')
                self.assertTrue(app.chatgpt_accounts.quota_rest_separator.winfo_manager())
                card = app.chatgpt_widgets['paid']['card']
                app.draw_chatgpt_accounts()
                self.assertIs(card, app.chatgpt_widgets['paid']['card'])
                with patch.object(app, 'active_provider_accounts', return_value={'openai': 'free'}):
                    app.animate_active_borders()
                    self.assertTrue(app.chatgpt_free_header.active_account_highlight)
                    self.assertFalse(app.chatgpt_header.active_account_highlight)
                app.telegram_token_entry.insert(0, '123:test-token')
                app.save_telegram_token()
                self.assertTrue(app.telegram_bot.token_saved())
                self.assertEqual(app.telegram_token_entry.get(), '')
                app.telegram_chat_entry.insert(0, '456')
                app.telegram_enabled.set(True)
                app.save_telegram_preferences()
                app.work = lambda fn, done, **kwargs: done(fn())
                with patch.object(app.telegram_bot, 'send_message') as send:
                    app.test_telegram()
                    send.assert_called_once()
                app.update()
                self.assertFalse(errors, errors)
            finally:
                app.closed = True
                app.destroy()
