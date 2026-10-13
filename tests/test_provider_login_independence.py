import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from provider_ui import ProviderSupport


class ProviderLoginIndependenceTests(unittest.TestCase):
    def make_app(self, google=None, claude=None, grok=None):
        return SimpleNamespace(
            pending_login=google, pending_chatgpt_login=('openai-state', 1),
            pending_claude_login=claude, pending_grok_login=grok,
            add_button=Mock(), add_chatgpt_button=Mock(),
            add_claude_button=Mock(), add_grok_button=Mock())

    def test_pending_chatgpt_login_does_not_disable_gemini_add_button(self):
        app = self.make_app()

        ProviderSupport.set_provider_login_buttons(app, True)

        app.add_button.configure.assert_called_once_with(state='normal')
        app.add_chatgpt_button.configure.assert_called_once_with(state='normal')

    def test_each_provider_disables_only_its_own_sign_in_button(self):
        app = self.make_app(google=('google-state', 1), claude=('claude-state', 1))

        ProviderSupport.set_provider_login_buttons(app, True)

        app.add_button.configure.assert_called_once_with(state='disabled')
        app.add_chatgpt_button.configure.assert_called_once_with(state='normal')
        app.add_claude_button.configure.assert_called_once_with(state='disabled')
        app.add_grok_button.configure.assert_called_once_with(state='normal')


if __name__ == '__main__':
    unittest.main()
