import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import App
from backend import Controller
from ui_locale import translate


class DisplaySettingsTests(unittest.TestCase):
    def test_higher_priority_accounts_move_to_top_without_recreating_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('app.Controller', lambda: Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')), \
                    patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), \
                    patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), \
                    patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'), \
                    patch.object(App, 'check_for_updates'), patch.object(App, 'refresh_chatgpt_accounts'):
                app = App()
                try:
                    app.items = [{'name': name, 'disabled': False, 'unavailable': False} for name in ('first', 'second')]
                    app.chatgpt_items = [{'name': name, 'email': name, 'disabled': False} for name in ('a', 'b')]
                    app.chatgpt_collapsed = False
                    app.draw_account_list()
                    app.draw_chatgpt_accounts()
                    google_card = app.account_widgets['second']['card']
                    gpt_card = app.chatgpt_widgets['b']['card']
                    app.change_account_priority(app.items[1], 'google', 1)
                    app.change_account_priority(app.chatgpt_items[1], 'openai', 1)
                    self.assertEqual(app.account_layout[0][0], 'second')
                    self.assertEqual(app._chatgpt_order[1], ('b', 'a'))
                    self.assertIs(app.account_list.pack_slaves()[0], google_card)
                    self.assertIs(app.chatgpt_accounts.pack_slaves()[1], gpt_card)
                    self.assertIs(app.account_widgets['second']['card'], google_card)
                    app.change_account_priority(app.items[0], 'google', 2)
                    self.assertEqual(app.account_layout[0][0], 'first')
                finally:
                    app.closed = True
                    app.destroy()

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
                    app.update_total_quota()
                    self.assertEqual(app.pool_summary_groups['google']['compact'].dot_values, (None, None))
                    self.assertTrue(app.pool_summary_groups['google']['compact'].winfo_manager())
                    compact = app.pool_summary_groups['google']['compact']
                    self.assertIs(compact.master, app.pool_summary_groups['google']['header'])
                    self.assertIn('1pcs', app.google_accounts_header.cget('text'))
                    dots = app.pool_summary_groups['google']['compact'].dot_widgets
                    first_image = dots[0].cget('image')
                    app.update_total_quota()
                    self.assertIs(dots[0].cget('image'), first_image)
                    app.draw_chatgpt_accounts()
                    app.draw_detail()
                    with patch('app.webbrowser.open') as open_release:
                        app.github_release_button.invoke()
                        open_release.assert_called_once_with('https://github.com/nikitaeight24family/Omni/releases/latest')
                    app.toggle_details()
                    app.settings_button.invoke()
                    self.assertFalse(app.details_collapsed)
                    self.assertEqual(app.view_switch.get(), 'Display settings')
                    self.assertTrue(app.display_settings._parent_frame.winfo_manager())
                    app.change_view('Account and quotas')
                    app.view_switch.set('Account and quotas')
                    app.toggle_chatgpt_accounts()
                    app.update()
                    self.assertLessEqual(compact.winfo_y() + compact.winfo_height(), compact.master.winfo_height())
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
                    # Polling identical data must not redraw or relayout cards and controls.
                    app.draw_account_list()
                    app.draw_chatgpt_accounts()
                    app.update_idletasks()
                    from contextlib import ExitStack
                    stable_widgets = [google_row['card'], google_row['button'], google_row['plan'],
                                      google_row['status'], google_row['priority'],
                                      google_row['priority'].priority_up, google_row['priority'].priority_down,
                                      app.chatgpt_widgets['gpt']['card'], app.chatgpt_widgets['gpt']['status']]
                    with ExitStack() as stack:
                        redraws = [stack.enter_context(patch.object(widget, '_draw', wraps=widget._draw))
                                   for widget in stable_widgets]
                        for _ in range(3):
                            app.draw_account_list()
                            app.draw_chatgpt_accounts()
                        for redraw in redraws:
                            redraw.assert_not_called()
                    with patch('app.simpledialog.askinteger', side_effect=AssertionError('Priority must not open a dialog')), patch.object(app, 'queue_policy'):
                        self.assertEqual(google_row['priority'].priority_down.cget('state'), 'disabled')
                        google_row['priority'].priority_up.invoke()
                        google_row['priority'].priority_up.invoke()
                        self.assertEqual(google_row['priority'].cget('text'), '2')
                        google_row['priority'].priority_down.invoke()
                    self.assertEqual(app.controller.preferences['account-priorities']['google'], 1)
                    self.assertEqual(google_row['priority'].cget('text'), '1')
                    from types import SimpleNamespace
                    bar = google_row['quotas'][('gemini', '5h')][1]
                    app.update()
                    self.assertEqual(bar.floor, 0)
                    event = SimpleNamespace(x_root=bar.winfo_rootx() + bar.winfo_width() * .7)
                    with patch.object(app, 'work'), patch.object(app, 'fetch_quota'):
                        bar.press(event)
                        self.assertEqual(bar.marker.cget('width'), 10)
                        self.assertEqual(bar.marker.cget('height'), 16)
                        app.update()
                        self.assertTrue(bar.bubble.winfo_viewable())
                        self.assertLessEqual(bar.bubble.winfo_rooty() + bar.bubble.winfo_height(), bar.winfo_rooty())
                        bar.drag(event)
                        self.assertEqual(bar.bubble.cget('text'), '70%')
                        bar.release(event)
                    self.assertEqual(bar.floor, 70)
                    self.assertEqual(app.controller.preferences['quota-floors']['google']['gemini']['5h'], 70)
                    self.assertFalse(bar.bubble.winfo_manager())
                    gpt_priority = app.chatgpt_widgets['gpt']['priority']
                    with patch('app.simpledialog.askinteger', side_effect=AssertionError('Priority must not open a dialog')), patch.object(app, 'refresh_chatgpt_accounts') as refresh:
                        gpt_priority.priority_up.invoke()
                        self.assertEqual(gpt_priority.cget('text'), '1')
                        refresh.assert_called_once()
                        app.controller.preferences['account-priorities']['gpt'] = 999
                        app.update_priority_counter(gpt_priority, app.chatgpt_items[0])
                        self.assertEqual(gpt_priority.priority_up.cget('state'), 'disabled')
                        gpt_priority.priority_up.invoke()
                        self.assertEqual(gpt_priority.cget('text'), '999')
                        gpt_priority.priority_down.invoke()
                        self.assertEqual(gpt_priority.cget('text'), '998')
                    self.assertIs(app.sidebar_footer.pack_slaves()[-1], app.tokenharbor_accounts)
                    footer_y = app.service.winfo_rooty()
                    app.toggle_google_accounts()
                    app.update()
                    self.assertEqual(app.service.winfo_rooty(), footer_y)
                    self.assertTrue(app.sidebar_spacer.winfo_manager())
                    self.assertTrue(app.google_compact.winfo_manager())
                    app.toggle_google_accounts()
                    app.update()
                    self.assertFalse(app.sidebar_spacer.winfo_manager())
                    self.assertFalse(app.google_compact.winfo_manager())
                    app.rename_entry.delete(0, 'end')
                    app.rename_entry.insert(0, 'Unsaved name')
                    app.service_variables['claude'].set(False)
                    app.set_service_visibility('claude')
                    self.assertFalse(claude_row.winfo_manager())
                    self.assertEqual(app.rename_entry.get(), 'Unsaved name')
                    app.service_variables['gemini'].set(False)
                    app.set_service_visibility('gemini')
                    app.update()
                    # Canvas children can stay mapped while their containing frame is hidden.
                    # Viewability includes the visibility of every ancestor.
                    self.assertFalse(google_card.winfo_viewable())
                    self.assertGreaterEqual(app.service.winfo_rooty(), footer_y)
                    self.assertTrue(gpt_card.winfo_viewable())
                    for provider in ('openai', 'tokenharbor'):
                        app.service_variables[provider].set(False)
                        app.set_service_visibility(provider)
                    app.update()
                    self.assertFalse(gpt_card.winfo_viewable())
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
                    self.assertEqual(app.account_list._parent_canvas.cget('bg'), '#191f2b')
                    self.assertEqual(app.items[0]['email'], 'private@example.com')
                    self.assertFalse(app.items[0]['disabled'])
                    saved = Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')
                    self.assertEqual(saved.preferences['theme'], 'dark')
                    self.assertEqual(saved.preferences['language'], 'en')
                    self.assertTrue(all(saved.preferences['visible-services'].values()))
                    self.assertEqual(saved.preferences['account-priorities'], {'google': 1, 'gpt': 998})
                finally:
                    app.closed = True
                    app.destroy()
