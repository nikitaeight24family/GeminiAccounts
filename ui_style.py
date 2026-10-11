"""Scoped widget adapters for display language and light/dark palettes."""
import tkinter as tk
from tkinter import messagebox, simpledialog
from types import SimpleNamespace
import customtkinter as native_ctk
from ui_locale import translate
from ui_render import queue_for
from ui_skin import StaticBoxEngine, paint_skin

LIGHT = {
    '#101728': '#ffffff', '#87a8ff': '#2757b4', '#3d4b64': '#cbd9ee',
    '#10141d': '#f4f6fa', '#191f2b': '#ffffff', '#222a38': '#eaf0f8',
    '#edf2fa': '#1b2638', '#9daec4': '#52647b', '#739aff': '#3465cf',
    '#66d7b0': '#147d61', '#202938': '#f1f5fb', '#344155': '#bbc7d8',
    '#303b50': '#dfe8f5', '#303e59': '#dce7fa', '#334158': '#cbd9ee',
    '#3a465c': '#a8b8cc', '#354157': '#d6dfec', '#43516a': '#b0bfd2',
    '#f7ca70': '#986100', '#ffbd93': '#a74319', '#bac9df': '#4a5f7b',
    '#334d77': '#d3e3ff', '#654332': '#f0dccb', '#293344': '#e3ebf6',
    '#f5c56b': '#986100', '#ff8d8d': '#bc3434', '#d98b6b': '#a65a36', '#183b32': '#d9f1e7', '#264268': '#dae7fd',
}
COLOR_KEYS = {'fg_color', 'bg_color', 'text_color', 'border_color', 'hover_color',
              'progress_color', 'button_color', 'button_hover_color', 'dropdown_fg_color',
              'dropdown_hover_color', 'dropdown_text_color', 'selected_color',
              'selected_hover_color', 'unselected_color', 'unselected_hover_color',
              'text_color_disabled', 'placeholder_text_color', 'checkmark_color'}


def style_for(widget):
    while widget is not None:
        style = vars(widget).get('_ui_style')
        if style is not None:
            return style
        widget = vars(widget).get('master')
    return None


class UIStyle:
    def __init__(self, root, preferences):
        self.root = root
        self.language = preferences.get('language', 'en')
        self.theme = preferences.get('theme', 'dark')
        root._ui_style = self
        native_ctk.set_appearance_mode(self.theme)

    def color(self, value, canvas=False):
        if not isinstance(value, str) or value.lower() not in LIGHT:
            return value
        light = LIGHT[value.lower()]
        return light if self.theme == 'light' else value

    def text(self, value):
        return translate(value, self.language)

    def apply(self, language=None, theme=None):
        if language is not None:
            self.language = language
        if theme is not None:
            self.theme = theme
        # Snapshot canonical sources before parent color propagation touches children.
        snapshots = []
        def collect(widget):
            if isinstance(widget, WidgetStyleMixin):
                selected = widget.get() if isinstance(widget, SelectorMixin) else None
                snapshots.append((widget, widget._ui_sources.copy(), selected))
            elif isinstance(widget, Canvas):
                snapshots.append((widget, None, None))
            for child in widget.winfo_children():
                collect(child)
        collect(self.root)
        native_ctk.set_appearance_mode(self.theme)
        keys = set(COLOR_KEYS) if theme is not None else set()
        if language is not None:
            keys.update(('text', 'placeholder_text', 'values', 'command'))
        for widget, sources, selected in snapshots:
            if sources is None:
                widget.refresh_style()
                continue
            relevant = {key: value for key, value in sources.items() if key in keys}
            # ScrollableFrame also owns a native parent canvas: refresh its background
            # even when the public frame reports the same transparent color.
            widget._ui_refreshing = isinstance(widget, native_ctk.CTkScrollableFrame)
            try:
                if relevant:
                    widget.configure(**relevant)
            finally:
                widget._ui_refreshing = False
                widget._ui_sources = sources
            if selected is not None and language is not None:
                widget.set(selected)


class WidgetStyleMixin:
    def _display(self, kwargs):
        style = style_for(self)
        if style is None:
            return kwargs
        result = dict(kwargs)
        for key, value in kwargs.items():
            if key in COLOR_KEYS:
                result[key] = style.color(value)
            elif key in ('text', 'placeholder_text'):
                result[key] = style.text(value) if getattr(self, '_ui_localize', True) else value
            elif key == 'values':
                result[key] = [style.text(value) for value in value]
            elif key == 'command' and isinstance(self, SelectorMixin) and value:
                result[key] = lambda selected, fn=value: fn(self._canonical(selected))
        return result

    def __init__(self, *args, **kwargs):
        if isinstance(self, native_ctk.CTkSegmentedButton):
            for key, value in {'fg_color': '#303b50', 'selected_color': '#334d77',
                               'selected_hover_color': '#303e59', 'unselected_color': '#303b50',
                               'unselected_hover_color': '#3d4b64', 'text_color': '#edf2fa'}.items():
                kwargs.setdefault(key, value)
        self._ui_localize = kwargs.pop('localize', True)
        self._ui_font_request = kwargs.get('font')
        self._ui_sources = {key: value for key, value in kwargs.items()
                            if key in COLOR_KEYS or key in ('text', 'placeholder_text', 'values', 'command')}
        # Constructors have not assigned master yet.
        parent = args[0] if args else kwargs.get('master')
        style = style_for(parent)
        if style is not None:
            self._ui_style = style
        super().__init__(*args, **self._display(kwargs))
        self._ui_render_ready = True
        if isinstance(self, (native_ctk.CTk, native_ctk.CTkToplevel)):
            self._windows_set_titlebar_icon()

    def _windows_set_titlebar_icon(self):
        # Every dialog gets the product icon, including CTk's delayed icon callback.
        from pathlib import Path
        import sys
        icon = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'app.ico'
        if icon.exists():
            self.iconbitmap(default=str(icon))
            self.iconbitmap(str(icon))

    def _windows_set_titlebar_color(self, color_mode):
        # DWM can recolor a live title bar. CTk hides/reopens the entire window
        # here, adding a blocking delay and causing a second progressive paint.
        import sys
        if not sys.platform.startswith('win') or getattr(self, '_deactivate_windows_window_header_manipulation', False):
            return
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        hwnd = user.GetParent(self.winfo_id())
        value = ctypes.c_int(color_mode.lower() == 'dark')
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        for attribute in (20, 19):
            if dwm(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        user.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.HANDLE, wintypes.UINT]
        user.RedrawWindow(hwnd, None, None, 0x401)  # frame + invalidate; event loop presents it

    def destroy(self):
        renderer = vars(self).get('_render_queue')
        if renderer is not None:
            renderer.close()
        return super().destroy()

    def _draw(self, no_color_updates=False):
        if isinstance(self, (native_ctk.CTkFrame, native_ctk.CTkButton, native_ctk.CTkLabel)) and hasattr(self, '_draw_engine'):
            if not isinstance(self._draw_engine, StaticBoxEngine):
                self._draw_engine = StaticBoxEngine(self._draw_engine)
        if not getattr(self, '_ui_render_ready', False):
            result = super()._draw(no_color_updates)
            if isinstance(getattr(self, '_draw_engine', None), StaticBoxEngine):
                paint_skin(self)
            return result
        queue_for(self).request(self, no_color_updates)

    def _render_now(self, no_color_updates=False):
        result = super()._draw(no_color_updates)
        if isinstance(getattr(self, '_draw_engine', None), StaticBoxEngine):
            paint_skin(self)
        return result

    def _on_enter(self, event=None):
        result = super()._on_enter(event)
        if isinstance(self, native_ctk.CTkButton) and self._hover:
            self._skin_hover = True
            self._draw()
        return result

    def _on_leave(self, event=None):
        result = super()._on_leave(event)
        if isinstance(self, native_ctk.CTkButton):
            self._skin_hover = False
            self._draw()
        return result

    def configure(self, **kwargs):
        if 'localize' in kwargs:
            self._ui_localize = kwargs.pop('localize')
        if '_ui_sources' not in vars(self):
            self._ui_sources = {}
        self._ui_sources.update({key: value for key, value in kwargs.items()
                                 if key in COLOR_KEYS or key in ('text', 'placeholder_text', 'values', 'command')})
        if getattr(self, '_ui_refreshing', False):
            return super().configure(**self._display(kwargs))
        changed = {}
        for key, value in self._display(kwargs).items():
            if key == 'font':
                if value == self._ui_font_request:
                    continue
                self._ui_font_request = value
            else:
                try:
                    if super().cget(key) == value:
                        continue
                except (ValueError, AttributeError, tk.TclError):
                    pass
            changed[key] = value
        if changed:
            return super().configure(**changed)


class SelectorMixin:
    def _canonical(self, value):
        style = style_for(self)
        if style:
            for original in self._ui_sources.get('values', []):
                if value in (original, translate(original, 'ru')):
                    return original
        return value

    def get(self):
        return self._canonical(super().get())

    def set(self, value, *args, **kwargs):
        style = style_for(self)
        return super().set(style.text(value) if style else value, *args, **kwargs)


ctk = SimpleNamespace(**{name: getattr(native_ctk, name) for name in dir(native_ctk) if not name.startswith('_')})
for name in ('CTk', 'CTkToplevel', 'CTkFrame', 'CTkScrollableFrame', 'CTkLabel', 'CTkButton',
             'CTkEntry', 'CTkTextbox', 'CTkCheckBox', 'CTkSwitch', 'CTkProgressBar', 'CTkSlider'):
    setattr(ctk, name, type(name, (WidgetStyleMixin, getattr(native_ctk, name)), {}))
for name in ('CTkOptionMenu', 'CTkSegmentedButton', 'CTkComboBox'):
    setattr(ctk, name, type(name, (SelectorMixin, WidgetStyleMixin, getattr(native_ctk, name)), {}))


class StableProgressBar(ctk.CTkProgressBar):
    def set(self, value, from_variable_callback=False):
        if self._variable is None and max(0, min(1, value)) == self.get():
            return
        return super().set(value, from_variable_callback=from_variable_callback)


ctk.CTkProgressBar = StableProgressBar


class Canvas(tk.Canvas):
    def __init__(self, *args, **kwargs):
        self._ui_options = dict(kwargs)
        self._ui_items = {}
        style = style_for(args[0] if args else kwargs.get('master'))
        if style:
            kwargs = {key: style.color(value, True) if key in ('bg', 'background') else value
                      for key, value in kwargs.items()}
        super().__init__(*args, **kwargs)

    def configure(self, cnf=None, **kwargs):
        self._ui_options.update(kwargs)
        style = style_for(self)
        if style:
            kwargs = {key: style.color(value, True) if key in ('bg', 'background') else value
                      for key, value in kwargs.items()}
        return super().configure(cnf, **kwargs)

    def _options_for_style(self, options):
        style = style_for(self)
        if not style:
            return options
        return {key: style.text(value) if key == 'text' else
                style.color(value, True) if key in ('fill', 'outline') else value
                for key, value in options.items()}

    def _create(self, itemType, args, kw):
        item = super()._create(itemType, args, self._options_for_style(kw))
        self._ui_items[item] = {key: value for key, value in kw.items() if key in ('text', 'fill', 'outline')}
        return item

    def itemconfigure(self, tagOrId, cnf=None, **kwargs):
        if kwargs:
            for item in self.find_withtag(tagOrId):
                self._ui_items.setdefault(item, {}).update({key: value for key, value in kwargs.items()
                                                           if key in ('text', 'fill', 'outline')})
        return super().itemconfigure(tagOrId, cnf, **self._options_for_style(kwargs))

    def delete(self, *items):
        for target in items:
            for item in self.find_withtag(target):
                self._ui_items.pop(item, None)
        return super().delete(*items)

    def refresh_style(self):
        self.configure(**{key: value for key, value in self._ui_options.items() if key in ('bg', 'background')})
        for item, options in self._ui_items.items():
            super().itemconfigure(item, **self._options_for_style(options))


class Dialogs:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        function = getattr(self.module, name)
        def call(*args, **kwargs):
            style = style_for(kwargs.get('parent') or tk._default_root)
            if style:
                args = tuple(style.text(arg) if isinstance(arg, str) else arg for arg in args)
                for key in ('title', 'message', 'prompt'):
                    if key in kwargs:
                        kwargs[key] = style.text(kwargs[key])
            return function(*args, **kwargs)
        return call


localized_messagebox = Dialogs(messagebox)
localized_simpledialog = Dialogs(simpledialog)
