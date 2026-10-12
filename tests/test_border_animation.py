import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app import App


class BorderAnimationTests(unittest.TestCase):
    def test_fast_tick_only_updates_visible_active_borders(self):
        active = {'card': Mock(), 'active_highlight': True}
        hidden = {'card': Mock(), 'active_highlight': True}
        idle = {'card': Mock(), 'active_highlight': False}
        active['card'].winfo_ismapped.return_value = True
        hidden['card'].winfo_ismapped.return_value = False
        app = SimpleNamespace(closed=False, account_widgets={'a': active, 'b': idle},
            chatgpt_widgets={'c': hidden}, draw_rainbow_border=Mock(), after=Mock(),
            animate_border_colors=Mock(), playback_icons={'reset-rainbow': list(range(180))})
        with patch('app.time.monotonic', return_value=4):
            App.animate_border_colors(app)
        app.draw_rainbow_border.assert_called_once_with(active, .5)
        app.after.assert_called_once_with(33, app.animate_border_colors)
        idle['card'].configure.assert_not_called()

    def test_visible_reset_buttons_share_fast_tick_and_hidden_buttons_are_skipped(self):
        visible, hidden = Mock(), Mock()
        visible.winfo_ismapped.return_value = True
        hidden.winfo_ismapped.return_value = False
        app = SimpleNamespace(closed=False, chatgpt_widgets={'a': {'reset_buttons': [visible, hidden]}},
            playback_icons={'reset-rainbow': list(range(180))}, after=Mock(), animate_border_colors=Mock())
        with patch('app.time.monotonic', return_value=1):
            App.animate_border_colors(app)
        visible.configure.assert_called_once_with(image=30)
        hidden.configure.assert_not_called()

    def test_closed_window_stops_animation(self):
        app = SimpleNamespace(closed=True, after=Mock())
        App.animate_border_colors(app)
        app.after.assert_not_called()
