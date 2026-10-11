"""A quota progress bar with a draggable minimum-remaining marker."""
from ui_style import ctk


class QuotaLimitBar(ctk.CTkFrame):
    def __init__(self, master, floor=0, command=None, **kwargs):
        progress_color = kwargs.pop('progress_color', '#66d7b0')
        track_color = kwargs.pop('fg_color', '#354157')
        kwargs.pop('height', None)
        super().__init__(master, height=18, fg_color='transparent', **kwargs)
        self.bar = ctk.CTkProgressBar(self, height=5, fg_color=track_color, progress_color=progress_color)
        self.bar.place(relx=0, rely=.5, relwidth=1, anchor='w')
        self.floor = floor
        self.command = command
        self.dragging = False
        # Keep the row height fixed while the handle grows inside it.
        self.marker = ctk.CTkFrame(self, width=4, height=10, corner_radius=2,
                                   fg_color='#739aff', border_width=1,
                                   border_color='#edf2fa', cursor='sb_h_double_arrow')
        self.marker.place(relx=floor / 100, rely=.5, anchor='center')
        # A row clips children above its bounds. Attach the tooltip to the window.
        self.bubble = ctk.CTkLabel(self.winfo_toplevel(), text='', height=24, width=44,
                                  corner_radius=7, fg_color='#303b50', text_color='#edf2fa',
                                  font=('Segoe UI', 11, 'bold'))
        for target in (self, self.bar, self.marker):
            target.bind('<ButtonPress-1>', self.press)
            target.bind('<B1-Motion>', self.drag)
            target.bind('<ButtonRelease-1>', self.release)
        self.bind('<Configure>', lambda event: self.place_marker(), add='+')
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
        half = self._apply_widget_scaling(5 if self.dragging else 2)
        position = max(half, min(max(half, self.winfo_width() - half),
                                 self.winfo_width() * self.floor / 100))
        self.marker.place(relx=0, rely=.5, anchor='center', x=self._reverse_widget_scaling(position))
        if self.dragging:
            self.bubble.configure(text=f'{self.floor}%')
            root = self.winfo_toplevel()
            x = self.winfo_rootx() - root.winfo_rootx() + position
            half_bubble = self.bubble._apply_widget_scaling(22)
            x = max(half_bubble, min(root.winfo_width() - half_bubble, x))
            y = self.winfo_rooty() - root.winfo_rooty() - self._apply_widget_scaling(2)
            self.bubble.place(x=self.bubble._reverse_widget_scaling(x),
                              y=self.bubble._reverse_widget_scaling(y), anchor='s')
            self.bubble.lift()

    def press(self, event):
        self.dragging = True
        parent = self.master
        while parent is not None:
            background = getattr(parent, '_ui_sources', {}).get('fg_color')
            if background and background != 'transparent':
                self.bubble.configure(bg_color=background)
                break
            parent = getattr(parent, 'master', None)
        self.marker.configure(width=10, height=16, corner_radius=5, fg_color='#87a8ff')
        self.marker._canvas.grab_set()
        self.place_marker()

    def drag(self, event):
        if not self.dragging:
            return
        fraction = (event.x_root - self.winfo_rootx()) / max(1, self.winfo_width())
        self.floor = round(max(0, min(1, fraction)) * 100)
        self.place_marker()

    def release(self, event):
        if not self.dragging:
            return
        self.drag(event)
        self.dragging = False
        self.marker._canvas.grab_release()
        self.marker.configure(width=4, height=10, corner_radius=2, fg_color='#739aff')
        self.place_marker()
        self.bubble.place_forget()
        if self.command:
            self.command(self.floor)

    def cleanup(self, event):
        if event.widget is self and self.bubble.winfo_exists():
            self.bubble.destroy()
