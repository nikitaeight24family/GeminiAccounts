import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from app import App


class CallbackPasteTests(unittest.TestCase):
    def test_paste_button_inserts_callback_without_submitting(self):
        app = SimpleNamespace(google_callback_busy=False,
            clipboard_get=Mock(return_value='  http://localhost:51121/oauth-callback?state=test&code=test  '),
            google_callback_entry=Mock(), google_callback_status=Mock())
        App.paste_google_callback(app)
        app.google_callback_entry.delete.assert_called_once_with(0, 'end')
        app.google_callback_entry.insert.assert_called_once_with(0, 'http://localhost:51121/oauth-callback?state=test&code=test')

    def test_russian_keyboard_virtual_v_pastes_once(self):
        app = SimpleNamespace(paste_google_callback=Mock())
        self.assertEqual(App.google_callback_paste_key(app, SimpleNamespace(keycode=86, keysym='Cyrillic_em')), 'break')
        app.paste_google_callback.assert_called_once_with()

    def test_accepted_single_use_callback_cannot_be_replaced(self):
        app = SimpleNamespace(google_callback_busy=True, clipboard_get=Mock())
        App.paste_google_callback(app)
        app.clipboard_get.assert_not_called()
