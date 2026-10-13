import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App
from telegram_notifications import TelegramBot, TelegramError


class TelegramTests(unittest.TestCase):
    def test_encrypted_storage_and_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = TelegramBot(Path(directory) / 'token.bin')
            bot.save_token('123:secret-value')
            self.assertNotIn(b'secret-value', bot.token_path.read_bytes())
            self.assertEqual(bot.load_token(), '123:secret-value')
            with patch('telegram_notifications.urllib.request.OpenerDirector.open', return_value=io.BytesIO(b'{"ok":true,"result":{}}')) as request:
                bot.send_message('456', 'test')
            self.assertIn(b'chat_id=456', request.call_args.args[0].data)
            with patch('telegram_notifications.urllib.request.OpenerDirector.open', side_effect=urllib.error.URLError('secret-value')):
                with self.assertRaises(TelegramError) as result:
                    bot.send_message('456', 'test')
                self.assertNotIn('secret-value', str(result.exception))

    def test_chat_discovery_and_missing_start(self):
        bot = TelegramBot('unused')
        bot._request = Mock(return_value=[{'update_id': 1, 'message': {'chat': {'id': 12}}},
                                         {'update_id': 3, 'message': {'chat': {'id': 34}}}])
        self.assertEqual(bot.discover_chat_id(), '34')
        bot._request.return_value = []
        with self.assertRaises(TelegramError):
            bot.discover_chat_id()

    def test_transition_deduplication_and_restart(self):
        app = SimpleNamespace(closed=False, controller=SimpleNamespace(preferences={}, save=Mock()),
                              _telegram_status_initialized=set(), send_telegram_account_alert=Mock())
        healthy = {'name': 'one', 'status': 'active'}
        blocked = {'name': 'one', 'status': 'banned'}
        observe = lambda rows: App.observe_account_statuses(app, 'openai', rows)
        observe([healthy])
        observe([blocked])
        observe([blocked])
        self.assertEqual(app.send_telegram_account_alert.call_count, 1)
        app._telegram_status_initialized.clear()
        observe([blocked])
        self.assertEqual(app.send_telegram_account_alert.call_count, 1)
        observe([healthy])
        observe([blocked])
        self.assertEqual(app.send_telegram_account_alert.call_count, 2)

    def test_unknown_quota_is_not_empty_but_either_openai_window_is(self):
        app = SimpleNamespace(quota_cache={})
        self.assertFalse(App.account_empty_quota(app, {'name': 'unknown'}))
        self.assertTrue(App.account_empty_quota(app, {'name': 'gpt', 'quota': {'windows': [
            {'remaining': 100}, {'remaining': 0}]}}))
        app.quota_cache['google'] = {'data': {'groups': [
            {'buckets': [{'remaining': 0}]}, {'buckets': [{'remaining': .7}]}]}}
        self.assertFalse(App.account_empty_quota(app, {'name': 'google'}))
        app.quota_cache['google']['data']['groups'][1]['buckets'][0]['remaining'] = 0
        self.assertTrue(App.account_empty_quota(app, {'name': 'google'}))
