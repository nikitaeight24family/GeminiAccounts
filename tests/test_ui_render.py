import tkinter as tk
import unittest
from unittest.mock import patch
from ui_style import ctk, UIStyle
from ui_render import queue_for


class RenderTests(unittest.TestCase):
    def test_thin_rounded_skins_with_border_larger_than_interior(self):
        from ui_skin import SkinCache
        root = tk.Tk()
        try:
            cache = SkinCache(root)
            for width, height, border in ((3, 8, 2), (8, 3, 2), (4, 8, 2), (1, 8, 2)):
                with self.subTest(width=width, height=height):
                    skin = cache.get((width, height, 2, border, '#202938', '#ffffff', '#7090ff'))
                    self.assertEqual((skin.width(), skin.height()), (width, height))
        finally:
            root.destroy()

    def test_static_card_skin_survives_value_changes_and_is_shared(self):
        root = ctk.CTk()
        try:
            UIStyle(root, {})
            cards = [ctk.CTkFrame(root, width=220, height=90, corner_radius=9,
                                  fg_color='#222a38', border_width=1, border_color='#344155') for _ in range(2)]
            for card in cards:
                card.pack()
                card.pack_propagate(False)
            value = ctk.CTkLabel(cards[0], text='50%', fg_color='transparent')
            value.pack()
            root.update()
            image = cards[0]._skin_image
            self.assertIs(image, cards[1]._skin_image)
            self.assertEqual(len(cards[0]._canvas.find_withtag('static_skin')), 1)
            builds = root._skin_cache.builds
            for percent in range(51, 100):
                value.configure(text=f'{percent}%')
                root.update_idletasks()
            self.assertEqual(root._skin_cache.builds, builds)
            self.assertIs(cards[0]._skin_image, image)
            self.assertFalse(cards[0]._canvas.find_withtag('inner_parts'))
        finally:
            root.destroy()

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
