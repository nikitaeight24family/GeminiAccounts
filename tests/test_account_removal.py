import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app import App
from backend import AccountError


class AccountRemovalTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(chatgpt_items=[{'name': 'codex-test+account.json'}],
            controller=SimpleNamespace(request=Mock(return_value={'status': 'ok'}),
                preferences={'labels': {'codex-test+account.json': 'test'}}, save=Mock()),
            display_name=Mock(return_value='OpenAI 6'), set_chatgpt_accounts=Mock())
        app.work = lambda fn, done, **kw: done(fn())
        return app

    def test_confirmed_removal_sends_exact_delete_and_updates_without_quota_calls(self):
        app = self.app()
        with patch('app.messagebox.askyesno', return_value=True), patch('app.ChatGPTAuth') as auth:
            auth.return_value.accounts.return_value = [{'name': 'other'}]
            App.remove_chatgpt_account(app, 'codex-test+account.json')
        app.controller.request.assert_called_once_with('/auth-files?name=codex-test%2Baccount.json', 'DELETE')
        app.set_chatgpt_accounts.assert_called_once_with([{'name': 'other'}])
        self.assertEqual(app.controller.preferences['labels'], {})
        auth.return_value.accounts_with_quotas.assert_not_called()

    def test_declined_confirmation_does_not_remove(self):
        app = self.app()
        with patch('app.messagebox.askyesno', return_value=False):
            App.remove_chatgpt_account(app, 'codex-test+account.json')
        app.controller.request.assert_not_called()

    def test_unconfirmed_gateway_removal_reports_failure(self):
        app = self.app()
        with patch('app.messagebox.askyesno', return_value=True), patch('app.ChatGPTAuth') as auth:
            auth.return_value.accounts.return_value = app.chatgpt_items
            with self.assertRaises(AccountError):
                App.remove_chatgpt_account(app, 'codex-test+account.json')
        app.set_chatgpt_accounts.assert_not_called()
