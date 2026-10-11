"""A quota progress bar with a draggable minimum-remaining marker."""
import tkinter as tk
from ui_style import ctk


class QuotaLimitBar(ctk.CTkFrame):
    def __init__(self, master, floor=0, command=None, **kwargs):
        progress_color = kwargs.pop('progress_color', '#66d7b0')
        track_color = kwargs.pop('fg_color', '#354157')
        kwargs.pop('height', None)
        super().__init__(master, height=12, fg_color='transparent', **kwargs)
        self.bar = ctk.CTkProgressBar(self, height=5, fg_color=track_color, progress_color=progress_color)
        self.bar.place(relx=0, rely=.5, relwidth=1, anchor='w')
        self.floor = floor
        self.command = command
        self.dragging = False
        self.marker = tk.Canvas(self, width=4, height=12, bg='#edf2fa', highlightthickness=0, cursor='sb_h_double_arrow')
        self.marker.place(relx=floor / 100, rely=.5, anchor='center', x=2 if floor == 0 else -2 if floor == 100 else 0)
        self.bubble = ctk.CTkLabel(master, text='', height=20, width=42, corner_radius=5,
                                  fg_color='#303b50', text_color='#edf2fa', font=('Segoe UI', 11, 'bold'))
        self.marker.bind('<ButtonPress-1>', self.press)
        self.marker.bind('<B1-Motion>', self.drag)
        self.marker.bind('<ButtonRelease-1>', self.release)
        self.bind('<Destroy>', self.cleanup, add='+')

    def set(self, value):
        self.bar.set(value)

    def get(self):
        return self.bar.get()

    def configure(self, **kwargs):
        for key in ('progress_color',):
            if key in kwargs and hasattr(self, 'bar'):
                self.bar.configure(**{key: kwargs.pop(key)})
        if kwargs:
            return super().configure(**kwargs)

    def cget(self, name):
        if name == 'progress_color':
            return self.bar.cget(name)
        return super().cget(name)

    def set_floor(self, floor):
        if self.dragging or floor == self.floor:
            return
        self.floor = floor
        self.place_marker()

    def place_marker(self):
        self.marker.place_configure(relx=self.floor / 100, x=2 if self.floor == 0 else -2 if self.floor == 100 else 0)
        if self.dragging:
            self.bubble.configure(text=f'{self.floor}%')
            x = self.winfo_x() + self.winfo_width() * self.floor / 100
            half = self._apply_widget_scaling(21)
            x = max(half, min(self.master.winfo_width() - half, x))
            self.bubble.place(x=self._reverse_widget_scaling(x),
                              y=self._reverse_widget_scaling(self.winfo_y() - 2), anchor='s')
            self.bubble.lift()

    def press(self, event):
        self.dragging = True
        self.marker.configure(width=8)
        self.marker.grab_set()
        self.place_marker()

    def drag(self, event):
        fraction = (event.x_root - self.winfo_rootx()) / max(1, self.winfo_width())
        self.floor = round(max(0, min(1, fraction)) * 100)
        self.place_marker()

    def release(self, event):
        if not self.dragging:
            return
        self.drag(event)
        self.dragging = False
        self.marker.grab_release()
        self.marker.configure(width=4)
        self.bubble.place_forget()
        if self.command:
            self.command(self.floor)

    def cleanup(self, event):
        if event.widget is self and self.bubble.winfo_exists():
            self.bubble.destroy()
