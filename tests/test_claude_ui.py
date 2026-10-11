import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from app import App
from backend import Controller
from ui_style import ctk


class ClaudeUITests(unittest.TestCase):
    def test_pool_cards_priority_active_model_privacy_and_collapsed_footer(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory)
            stack.enter_context(patch('app.Controller',lambda:Controller(proxy_dir=root/'proxy',data_dir=root/'data')))
            for method in ('connection_settings','refresh','fetch_quota','fetch_models','start_activity','queue_policy','check_for_updates','refresh_chatgpt_accounts','refresh_claude_accounts'):
                stack.enter_context(patch.object(App,method))
            app=App()
            try:
                app.claude_items=[{'name':name,'email':name+'@example.com','provider':'claude','disabled':False,
                                  'quota':{'plan_type':'Max 5x','windows':[{'label':'5h','remaining':70,'reset_at':time.time()+1000},
                                  {'label':'1w','remaining':85,'reset_at':time.time()+600000}]}}
                                 for name in ('one','two')]
                panel=app.claude_panel;panel.collapsed=False;panel.render();app.update()
                row=panel.rows['two'];card=row['card'];bar=row['windows']['5h'][1]
                self.assertTrue(card.winfo_viewable())
                self.assertEqual(row['plan'].cget('text').strip(),'Max 5x')
                with patch.object(app,'refresh_claude_accounts'):
                    row['priority'].priority_up.invoke()
                app.update()
                self.assertIs(panel.body.pack_slaves()[0],card)
                self.assertIs(panel.rows['two']['card'],card)
                self.assertIs(panel.rows['two']['windows']['5h'][1],bar)
                now=datetime.now(timezone.utc)
                app.activity_state['latest']={'claude-sonnet-4-6':{'name':'two','model':'claude-sonnet-4-6','at':now.isoformat()}}
                app.gateway_jobs=[{'model':'claude-sonnet-4-6','state':'running'}];app.gateway_jobs_checked=time.monotonic()
                panel.animate();app.update()
                self.assertTrue(row['active_highlight'])
                self.assertTrue(row['model'].cget('text'))
                footer=app.sidebar_footer.winfo_rooty()
                panel.toggle();app.update()
                self.assertEqual(app.sidebar_footer.winfo_rooty(),footer)
                self.assertFalse(card.winfo_viewable())
                self.assertTrue(panel.compact.winfo_viewable())
                app.toggle_account_names();app.update()
                self.assertRegex(row['heading'].cget('text'),r'^Claude [0-9]+$')
                self.assertIs(app.sidebar_footer.pack_slaves()[-1],app.tokenharbor_accounts)
                app.set_theme('Light');app.update();app.set_theme('Dark');app.update()
                self.assertEqual(panel.body._parent_canvas.cget('bg'),'#191f2b')
                app.service_variables['claude'].set(False);app.set_service_visibility('claude');app.update()
                self.assertFalse(panel.winfo_viewable())
                self.assertFalse(app.pool_summary_groups['claude-native']['frame'].winfo_viewable())
            finally:
                app.closed=True;app.destroy()

    def test_root_and_every_dialog_keep_omni_icon(self):
        root=ctk.CTk()
        dialog=ctk.CTkToplevel(root)
        try:
            import ctypes
            from ctypes import wintypes
            user = ctypes.windll.user32
            gdi = ctypes.windll.gdi32
            user.GetParent.argtypes = [wintypes.HWND]
            user.GetParent.restype = wintypes.HWND
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
            user.SendMessageW.restype = ctypes.c_void_p
            user.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user.LoadImageW.restype = ctypes.c_void_p
            class IconInfo(ctypes.Structure):
                _fields_ = [('is_icon', wintypes.BOOL), ('x', wintypes.DWORD), ('y', wintypes.DWORD), ('mask', ctypes.c_void_p), ('color', ctypes.c_void_p)]
            class Bitmap(ctypes.Structure):
                _fields_ = [('type', wintypes.LONG), ('width', wintypes.LONG), ('height', wintypes.LONG), ('stride', wintypes.LONG), ('planes', wintypes.WORD), ('depth', wintypes.WORD), ('bits', ctypes.c_void_p)]
            user.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(IconInfo)]
            gdi.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            gdi.GetBitmapBits.argtypes = [ctypes.c_void_p, wintypes.LONG, ctypes.c_void_p]
            gdi.DeleteObject.argtypes = [ctypes.c_void_p]
            user.DestroyIcon.argtypes = [ctypes.c_void_p]
            def pixels(handle):
                info = IconInfo()
                self.assertTrue(user.GetIconInfo(handle, ctypes.byref(info)))
                try:
                    bitmap = Bitmap()
                    self.assertTrue(gdi.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap)))
                    buffer = ctypes.create_string_buffer(bitmap.stride*bitmap.height)
                    self.assertTrue(gdi.GetBitmapBits(info.color, len(buffer), buffer))
                    return bitmap.width, bitmap.height, buffer.raw
                finally:
                    gdi.DeleteObject(info.mask)
                    gdi.DeleteObject(info.color)
            import tkinter as tk
            reference = tk.Toplevel(root)
            reference.iconbitmap(str(Path('app.ico').resolve()))
            root.update()
            expected_pixels = pixels(user.SendMessageW(user.GetParent(reference.winfo_id()),0x7f,1,0))
            reference.destroy()
            for window in (root,dialog):
                hwnd = user.GetParent(window.winfo_id())
                handle = user.SendMessageW(hwnd, 0x7f, 1, 0)
                self.assertTrue(handle)
                width,height,data = pixels(handle)
                self.assertEqual((width,height,data), expected_pixels)
                window._windows_set_titlebar_icon()
                self.assertEqual(pixels(user.SendMessageW(hwnd,0x7f,1,0)), expected_pixels)
        finally:
            dialog.destroy();root.destroy()
