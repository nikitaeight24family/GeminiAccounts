import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import App
from backend import Controller
from ui_locale import translate


class DisplaySettingsTests(unittest.TestCase):
    def test_footer_stays_at_bottom_at_small_windows_and_multiple_scales(self):
        import customtkinter as native_ctk
        for scale in (1, .8, 1.25):
            native_ctk.set_widget_scaling(scale)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch('app.Controller', lambda: Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')), \
                        patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), \
                        patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), \
                        patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'), patch.object(App, 'check_for_updates'):
                    app = App()
                    try:
                        app.items = [{'name': 'google', 'disabled': False, 'unavailable': False}]
                        app.draw_account_list()
                        for size in ('990x680', '1120x760', '1120x1000'):
                            with self.subTest(scale=scale, size=size):
                                app.geometry(size)
                                app.update()
                                def bottom_gap():
                                    return app.sidebar.winfo_rooty() + app.sidebar.winfo_height() - (app.sidebar_footer.winfo_rooty() + app.sidebar_footer.winfo_height())
                                before = bottom_gap()
                                app.toggle_google_accounts()
                                app.update()
                                self.assertEqual(bottom_gap(), before)
                                app.toggle_google_accounts()
                                app.update()
                                self.assertEqual(bottom_gap(), before)
                                app.visible_services.update(gemini=False, claude=False)
                                app.apply_service_visibility()
                                app.update()
                                self.assertEqual(bottom_gap(), before)
                                app.visible_services.update(gemini=True, claude=True)
                                app.apply_service_visibility()
                                app.update()
                                self.assertEqual(bottom_gap(), before)
                    finally:
                        app.closed = True
                        app.destroy()
            native_ctk.set_widget_scaling(1)

    def test_google_paid_tier_wins_and_unknown_is_not_assumed_free(self):
        self.assertEqual(Controller.parse_subscription({'paidTier': {'id': 'g1-ultra-tier'},
                                                       'currentTier': {'id': 'free-tier'}}), 'AI Ultra')
        self.assertEqual(Controller.parse_subscription({'currentTier': {'id': 'g1-pro-tier'}}), 'AI Pro')
        self.assertEqual(Controller.parse_subscription({'currentTier': {'id': 'free-tier'}}), 'Free')
        self.assertIsNone(Controller.parse_subscription({'allowedTiers': [{'id': 'free-tier'}]}))
        self.assertEqual(Controller.parse_subscription({'currentTier': {'id': 'new-tier', 'name': 'New plan'}}), 'New plan')
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(data_dir=directory)
            controller.request = Mock(return_value={'status_code': 200, 'body': json.dumps({'paidTier': {'id': 'g1-pro-tier'}})})
            account = {'name': 'one', 'auth_index': 'index'}
            self.assertEqual(controller.subscription(account), 'AI Pro')
            self.assertEqual(controller.subscription(account), 'AI Pro')
            self.assertEqual(controller.request.call_count, 1)
            self.assertTrue(controller.request.call_args.args[2]['url'].endswith(':loadCodeAssist'))

    def test_translation_preserves_addresses_and_model_names(self):
        self.assertEqual(translate('Display settings', 'ru'), 'Настройки отображения')
        self.assertEqual(translate('Available · 232 responses', 'ru'), 'Доступен · 232 ответов')
        self.assertEqual(translate('active@example.com · gpt-6.1-sol', 'ru'), 'active@example.com · gpt-6.1-sol')
        self.assertEqual(translate('Display settings', 'en'), 'Display settings')

    def test_visibility_theme_and_language_preserve_accounts_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('app.Controller', lambda: Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')), \
                    patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), \
                    patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), \
                    patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'):
                app = App()
                try:
                    app.items = [{'name': 'google', 'email': 'private@example.com', 'disabled': False, 'unavailable': False}]
                    app.chatgpt_items = [{'name': 'gpt', 'email': 'gpt@example.com', 'disabled': False,
                                         'quota': {'plan_type': 'pro'}}]
                    app.quota_cache['google'] = {'data': {'subscription': 'AI Ultra'}}
                    app.selected = 'google'
                    app.draw_account_list()
                    app.draw_chatgpt_accounts()
                    app.draw_detail()
                    app.toggle_chatgpt_accounts()
                    app.update()
                    google_card = app.account_widgets['google']['card']
                    gpt_card = app.chatgpt_widgets['gpt']['card']
                    claude_row = app.account_widgets['google']['quota_rows'][('claude', 'weekly')]
                    self.assertIn('AI Ultra', app.account_widgets['google']['plan'].cget('text'))
                    app.update_idletasks()
                    google_row = app.account_widgets['google']
                    self.assertNotIn('●', google_row['button'].cget('text'))
                    self.assertIs(google_row['button'].cget('image'), app.provider_icons['antigravity'])
                    self.assertIs(google_row['plan'].master, google_row['status'].master)
                    self.assertIs(app.google_accounts_header.cget('image'), app.provider_icons['antigravity'])
                    self.assertGreaterEqual(google_row['plan'].winfo_rooty(),
                                            google_row['button'].winfo_rooty() + google_row['button'].winfo_height())
                    self.assertIn('Pro', app.chatgpt_widgets['gpt']['plan'].cget('text'))
                    self.assertIs(app.sidebar_footer.pack_slaves()[-1], app.tokenharbor_accounts)
                    footer_y = app.service.winfo_rooty()
                    app.toggle_google_accounts()
                    app.update()
                    self.assertEqual(app.service.winfo_rooty(), footer_y)
                    self.assertTrue(app.sidebar_spacer.winfo_manager())
                    app.toggle_google_accounts()
                    app.update()
                    self.assertFalse(app.sidebar_spacer.winfo_manager())
                    app.rename_entry.delete(0, 'end')
                    app.rename_entry.insert(0, 'Unsaved name')
                    app.service_variables['claude'].set(False)
                    app.set_service_visibility('claude')
                    self.assertFalse(claude_row.winfo_manager())
                    self.assertEqual(app.rename_entry.get(), 'Unsaved name')
                    app.service_variables['gemini'].set(False)
                    app.set_service_visibility('gemini')
                    app.update()
                    self.assertFalse(google_card.winfo_ismapped())
                    self.assertGreaterEqual(app.service.winfo_rooty(), footer_y)
                    self.assertTrue(gpt_card.winfo_ismapped())
                    for provider in ('openai', 'tokenharbor'):
                        app.service_variables[provider].set(False)
                        app.set_service_visibility(provider)
                    app.update()
                    self.assertFalse(gpt_card.winfo_ismapped())
                    for provider in ('gemini', 'claude', 'openai', 'tokenharbor'):
                        app.service_variables[provider].set(True)
                        app.set_service_visibility(provider)
                    app.update()
                    self.assertIs(google_card, app.account_widgets['google']['card'])
                    self.assertIs(gpt_card, app.chatgpt_widgets['gpt']['card'])
                    self.assertTrue(claude_row.winfo_manager())
                    self.assertIs(app.sidebar_footer.pack_slaves()[-1], app.tokenharbor_accounts)
                    app.set_theme('Light')
                    app.set_language('Русский')
                    app.update()
                    self.assertEqual(app.cget('fg_color'), '#f4f6fa')
                    self.assertEqual(app.chatgpt_widgets['gpt']['plan'].cget('text_color'), '#1b2638')
                    self.assertEqual(app.view_switch.get(), 'Account and quotas')
                    self.assertEqual(app.theme_control.get(), 'Light')
                    self.assertEqual(app.language_control.get(), 'Русский')
                    self.assertEqual(app.title(), 'Omni')
                    self.assertEqual(app.pool_button.cget('text'), 'Использовать все аккаунты')
                    self.assertEqual(app.forecast_canvas.cget('bg'), '#ffffff')
                    self.assertEqual(app.rename_entry.get(), 'Unsaved name')
                    app.change_view('Display settings')
                    self.assertTrue(app.display_settings._parent_frame.winfo_manager())
                    app.set_language('English')
                    app.set_theme('Dark')
                    self.assertEqual(app.pool_button.cget('text'), 'Use all • automatic routing')
                    self.assertEqual(app.cget('fg_color'), '#10141d')
                    self.assertEqual(app.items[0]['email'], 'private@example.com')
                    self.assertFalse(app.items[0]['disabled'])
                    saved = Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')
                    self.assertEqual(saved.preferences['theme'], 'dark')
                    self.assertEqual(saved.preferences['language'], 'en')
                    self.assertTrue(all(saved.preferences['visible-services'].values()))
                finally:
                    app.closed = True
                    app.destroy()
