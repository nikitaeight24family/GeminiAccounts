"""Scoped widget adapters for display language and light/dark palettes."""
import tkinter as tk
from tkinter import messagebox, simpledialog
from types import SimpleNamespace
import customtkinter as native_ctk
from ui_locale import translate

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
        native_ctk.set_appearance_mode(self.theme)
        def visit(widget):
            if isinstance(widget, WidgetStyleMixin):
                sources = getattr(widget, '_ui_sources', {}).copy()
                selected = widget.get() if isinstance(widget, SelectorMixin) else None
                if sources:
                    widget.configure(**sources)
                if selected is not None:
                    widget.set(selected)
            if isinstance(widget, Canvas):
                widget.refresh_style()
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)


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
        self._ui_sources = {key: value for key, value in kwargs.items()
                            if key in COLOR_KEYS or key in ('text', 'placeholder_text', 'values', 'command')}
        # Constructors have not assigned master yet.
        parent = args[0] if args else kwargs.get('master')
        style = style_for(parent)
        if style is not None:
            self._ui_style = style
        super().__init__(*args, **self._display(kwargs))

    def configure(self, **kwargs):
        if 'localize' in kwargs:
            self._ui_localize = kwargs.pop('localize')
        if '_ui_sources' not in vars(self):
            self._ui_sources = {}
        self._ui_sources.update({key: value for key, value in kwargs.items()
                                 if key in COLOR_KEYS or key in ('text', 'placeholder_text', 'values', 'command')})
        return super().configure(**self._display(kwargs))


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

    def set(self, value):
        style = style_for(self)
        return super().set(style.text(value) if style else value)


ctk = SimpleNamespace(**{name: getattr(native_ctk, name) for name in dir(native_ctk) if not name.startswith('_')})
for name in ('CTk', 'CTkToplevel', 'CTkFrame', 'CTkScrollableFrame', 'CTkLabel', 'CTkButton',
             'CTkEntry', 'CTkTextbox', 'CTkCheckBox', 'CTkSwitch', 'CTkProgressBar', 'CTkSlider'):
    setattr(ctk, name, type(name, (WidgetStyleMixin, getattr(native_ctk, name)), {}))
for name in ('CTkOptionMenu', 'CTkSegmentedButton', 'CTkComboBox'):
    setattr(ctk, name, type(name, (SelectorMixin, WidgetStyleMixin, getattr(native_ctk, name)), {}))


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
