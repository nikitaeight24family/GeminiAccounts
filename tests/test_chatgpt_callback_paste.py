import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app import ACCENT, App, TEXT


class ChatGPTCallbackPasteTests(unittest.TestCase):
    def test_paste_button_inserts_clipboard_and_confirms_it(self):
        entry = Mock()
        status = Mock()
        app = SimpleNamespace(chatgpt_callback_busy=False,
            clipboard_get=Mock(return_value='  http://localhost:1455/auth/callback?state=s&code=abc  '),
            chatgpt_callback_entry=entry, chatgpt_callback_status=status)

        App.paste_chatgpt_callback(app)

        entry.delete.assert_called_once_with(0, 'end')
        entry.insert.assert_called_once_with(0, 'http://localhost:1455/auth/callback?state=s&code=abc')
        entry.focus_set.assert_called_once_with()
        status.configure.assert_called_once_with(text='Callback pasted. Click Complete sign-in.', text_color=TEXT)

    def test_paste_does_not_read_clipboard_while_single_use_submission_is_pending(self):
        clipboard = Mock()
        app = SimpleNamespace(chatgpt_callback_busy=True, clipboard_get=clipboard)

        App.paste_chatgpt_callback(app)

        clipboard.assert_not_called()

    def test_finishing_sign_in_clears_single_use_paste_guard(self):
        app = SimpleNamespace(chatgpt_callback_busy=True, pending_chatgpt_login=('state', 1),
            chatgpt_pending_store=SimpleNamespace(remove=Mock(), all=Mock(return_value=[])),
            _activate_chatgpt_login=lambda state: setattr(app, 'pending_chatgpt_login', None),
            set_provider_login_buttons=lambda enabled: None,
            add_button=Mock(), add_chatgpt_button=Mock(), notice=Mock(),
            chatgpt_login_window=SimpleNamespace(winfo_exists=Mock(return_value=False)))

        App.finish_chatgpt_login(app, 'Sign-in failed.', False)

        self.assertFalse(app.chatgpt_callback_busy)
        self.assertIsNone(app.pending_chatgpt_login)

    def test_success_message_distinguishes_other_pending_sign_ins(self):
        status = Mock()
        login_window = SimpleNamespace(winfo_exists=Mock(return_value=True), destroy=Mock())
        controller = SimpleNamespace(preferences={}, save=Mock())
        app = SimpleNamespace(chatgpt_callback_busy=True, pending_chatgpt_login=('done', 1),
            chatgpt_pending_store=SimpleNamespace(remove=Mock(), all=Mock(return_value=[{'state': 'other'}])),
            _activate_chatgpt_login=Mock(), set_provider_login_buttons=Mock(),
            chatgpt_login_window=login_window, _show_chatgpt_login_window=Mock(),
            chatgpt_callback_status=status, ui_style=SimpleNamespace(text=lambda value: value),
            after=Mock(), poll_chatgpt_login=Mock(), notice=Mock(), chatgpt_collapsed=True, controller=controller,
            refresh_new_chatgpt_accounts=Mock())

        App.finish_chatgpt_login(app, 'ChatGPT account added.', True, 'done')

        status.configure.assert_called_with(
            text='ChatGPT account added. Active sign-in attempts remaining: 1', text_color=ACCENT)


if __name__ == '__main__':
    unittest.main()
