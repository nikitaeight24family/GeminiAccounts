"""Retained rendering: merge widget changes and present them at the next idle frame."""
import tkinter as tk
import customtkinter as native_ctk
from customtkinter.windows.widgets import ctk_scrollable_frame, ctk_textbox
from customtkinter.windows.widgets.core_rendering import DrawEngine
from customtkinter.windows.widgets.core_widget_classes import CTkBaseClass
from customtkinter.windows.widgets.appearance_mode import CTkAppearanceModeBaseClass

# Retained vector paths replace the many font-glyph canvas items per rounded box.
DrawEngine.preferred_drawing_method = "polygon_shapes"


def _retained_appearance(widget, mode_string):
    CTkAppearanceModeBaseClass._set_appearance_mode(widget, mode_string)
    widget._draw()


# CTk creates private native children (segmented-button cells, scroll containers).
# They must obey the same no-nested-event-loop rule as our public adapters.
CTkBaseClass._set_appearance_mode = _retained_appearance


class RenderQueue:
    def __init__(self, root):
        self.root = root
        self.pending = {}
        self.job = None
        self.frames = 0
        self.draws = 0

    def close(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        self.pending.clear()

    def request(self, widget, no_color_updates=False):
        self.pending[widget] = self.pending.get(widget, True) and no_color_updates
        if self.job is None:
            self.job = self.root.after_idle(self.flush)

    def flush(self):
        self.job = None
        pending, self.pending = self.pending, {}
        self.frames += 1
        for widget, no_color_updates in pending.items():
            try:
                if widget.winfo_exists():
                    widget._render_now(no_color_updates)
                    self.draws += 1
            except tk.TclError:
                if widget.winfo_exists():
                    raise


def queue_for(widget):
    root = widget._root()
    if not hasattr(root, '_render_queue'):
        root._render_queue = RenderQueue(root)
    return root._render_queue


class RetainedScrollbar(native_ctk.CTkScrollbar):
    """Do not pump the Tk event loop from inside a scrollbar paint.

    CTk's original draw calls canvas.update_idletasks(), which recursively paints
    partial layouts and runs more scrollbar draws. Tk presents the finished frame
    itself when control returns to its event loop.
    """
    def _draw(self, no_color_updates=False):
        start, end = self._get_scrollbar_values_for_minimum_pixel_size()
        recolor = self._draw_engine.draw_rounded_scrollbar(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            self._apply_widget_scaling(self._border_spacing), start, end, self._orientation)
        if not no_color_updates or recolor:
            color = self._button_hover_color if self._hover_state else self._button_color
            self._canvas.itemconfig('scrollbar_parts', fill=self._apply_appearance_mode(color),
                                    outline=self._apply_appearance_mode(color))
            bg = self._bg_color if self._fg_color == 'transparent' else self._fg_color
            bg = self._apply_appearance_mode(bg)
            self._canvas.configure(bg=bg)
            self._canvas.itemconfig('border_parts', fill=bg, outline=bg)


# ScrollableFrame constructs its scrollbar through this factory. Scope the change
# to CTk scrollbars; never replace Tk's event processing methods globally.
ctk_scrollable_frame.CTkScrollbar = RetainedScrollbar
ctk_textbox.CTkScrollbar = RetainedScrollbar
native_ctk.CTkScrollbar = RetainedScrollbar


class RetainedOptionMenu(native_ctk.CTkOptionMenu):
    def _draw(self, no_color_updates=False):
        recolor = self._draw_engine.draw_rounded_rect_with_border_vertical_split(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius), 0,
            self._apply_widget_scaling(self._current_width-self._current_height))
        arrow = self._draw_engine.draw_dropdown_arrow(
            self._apply_widget_scaling(self._current_width-self._current_height/2),
            self._apply_widget_scaling(self._current_height/2),
            self._apply_widget_scaling(self._current_height/3))
        if not no_color_updates or recolor or arrow:
            self._canvas.configure(bg=self._apply_appearance_mode(self._bg_color))
            for tag, color in (('inner_parts_left', self._fg_color),
                               ('inner_parts_right', self._button_color)):
                color = self._apply_appearance_mode(color)
                self._canvas.itemconfig(tag, outline=color, fill=color)
            color = self._text_color_disabled if self._state == tk.DISABLED else self._text_color
            color = self._apply_appearance_mode(color)
            self._text_label.configure(fg=color, bg=self._apply_appearance_mode(self._fg_color))
            self._canvas.itemconfig('dropdown_arrow', fill=color)


native_ctk.CTkOptionMenu = RetainedOptionMenu
