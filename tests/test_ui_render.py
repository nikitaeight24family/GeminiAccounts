import tkinter as tk
import unittest
from unittest.mock import patch
from ui_style import ctk, UIStyle
from ui_render import queue_for


class RenderTests(unittest.TestCase):
    def test_changes_are_merged_and_destroyed_widgets_are_discarded(self):
        root = ctk.CTk()
        try:
            label = ctk.CTkLabel(root, text='before')
            label.pack()
            root.update()
            with patch.object(label, '_render_now', wraps=label._render_now) as draw:
                for color in ('#739aff', '#66d7b0', '#f7ca70'):
                    label.configure(text_color=color)
                draw.assert_not_called()
                root.update_idletasks()
                self.assertEqual(draw.call_count, 1)
                self.assertEqual(label.cget('text_color'), '#f7ca70')
            label.configure(text_color='#739aff')
            label.destroy()
            root.update_idletasks()
            self.assertFalse(queue_for(root).pending)
        finally:
            root.destroy()

    def test_theme_changes_never_pump_a_nested_event_loop(self):
        root = ctk.CTk()
        try:
            style = UIStyle(root, {})
            frame = ctk.CTkScrollableFrame(root)
            frame.pack()
            ctk.CTkOptionMenu(frame, values=['one', 'two']).pack()
            ctk.CTkTextbox(frame).pack()
            ctk.CTkSegmentedButton(frame, values=['one', 'two']).pack()
            root.update()
            # Include CTk's private native children, not just the public adapters.
            with patch.object(tk.Misc, 'update_idletasks', side_effect=AssertionError('Nested paint')):
                style.apply(theme='light')
                style.apply(theme='dark')
            root.update()
            self.assertTrue(frame.winfo_viewable())
            self.assertEqual(frame.winfo_rgb(frame._parent_canvas.cget('bg')), frame.winfo_rgb('#2b2b2b'))
        finally:
            root.destroy()
