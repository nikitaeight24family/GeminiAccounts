import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from app import App
from backend import Controller, AccountError


class GoogleLoginUITests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        root = Path(directory)
        self.stack.enter_context(patch('app.Controller', lambda: Controller(proxy_dir=root/'proxy', data_dir=root/'data')))
        for method in ('refresh', 'fetch_quota', 'fetch_models', 'start_activity', 'queue_policy', 'connection_settings', 'check_for_updates', 'poll_login'):
            self.stack.enter_context(patch.object(App, method))
        self.browser = self.stack.enter_context(patch('app.webbrowser.open'))
        self.app = App()
        self.app.work = lambda fn, done, mutation=False: done(fn())

    def tearDown(self):
        self.app.closed = True
        if hasattr(self.app, 'login_window') and self.app.login_window.winfo_exists():
            self.app.login_window.destroy()
        self.app.destroy()
        self.stack.close()

    def start(self):
        self.app.login_started(('https://accounts.google.com/o/oauth2/auth?state=current', 'current'))
        self.app.update()

    def test_manual_profile_link_and_single_submission_wait_for_confirmation(self):
        self.start()
        self.browser.assert_not_called()
        self.app.google_copy_link_button.invoke()
        self.assertEqual(self.app.clipboard_get(), self.app.login_url)
        button = self.app.google_callback_button
        self.assertTrue(button.winfo_viewable())
        self.assertLess(button.winfo_y()+button.winfo_height(), self.app.login_window.winfo_height())
        callback = 'Blocked URL: http://localhost:51121/oauth-callback?state=current&code=secret'
        self.app.google_callback_entry.insert(0, callback)
        complete = self.app.controller.complete_google_login = Mock(return_value={'status': 'ok', 'completed': False})
        button.invoke()
        complete.assert_called_once_with(callback, 'current')
        self.assertEqual(self.app.google_callback_entry.get(), '')
        self.assertEqual(button.cget('state'), 'disabled')
        self.assertIsNotNone(self.app.pending_login)
        self.app.google_callback_entry.insert(0, callback)
        self.app.submit_google_callback()
        self.assertEqual(complete.call_count, 1)

    def test_invalid_callback_shows_inline_error_and_allows_correction(self):
        self.start()
        self.app.controller.complete_google_login = Mock(side_effect=AccountError('This callback belongs to another sign-in. Use the current link.'))
        self.app.google_callback_entry.insert(0, 'wrong callback')
        self.app.google_callback_button.invoke()
        self.assertIn('another sign-in', self.app.google_callback_status.cget('text'))
        self.assertEqual(self.app.google_callback_button.cget('state'), 'normal')
        self.assertFalse(self.app.google_callback_busy)

    def test_browser_opens_only_after_explicit_click_and_callback_finishes_flow(self):
        self.start()
        self.browser.assert_not_called()
        self.app.google_open_browser_button.invoke()
        self.browser.assert_called_once_with(self.app.login_url)
        self.app.controller.complete_google_login = Mock(return_value={'status': 'ok', 'completed': True})
        self.app.google_callback_entry.insert(0, 'callback')
        with patch.object(self.app, 'finish_login') as finish:
            self.app.google_callback_button.invoke()
            finish.assert_called_once_with('Account saved. You can select it for Claude.', True)
