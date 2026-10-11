"""Immutable raster skins; changing text never rebuilds card decoration."""
from collections import OrderedDict
from PIL import Image, ImageDraw, ImageTk


class SkinCache:
    def __init__(self, root):
        self.root = root
        self.images = OrderedDict()
        self.bytes = 0
        self.builds = 0

    def get(self, key):
        if key in self.images:
            self.images.move_to_end(key)
            return self.images[key]
        width, height, radius, border, background, fill, outline = key
        image = Image.new('RGB', (width, height), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, width-1, height-1), radius,
                               fill=outline if border else fill)
        if border and width > border*2 and height > border*2:
            draw.rounded_rectangle((border, border, width-border-1, height-border-1),
                                   max(0, radius-border), fill=fill)
        # Supersample only the curved corners, never the whole large panel.
        extent = min(radius+border+2, width//2, height//2)
        if radius and extent > 0:
            size = extent*2
            corner = Image.new('RGB', (size*3, size*3), background)
            brush = ImageDraw.Draw(corner)
            brush.rounded_rectangle((0, 0, size*3-1, size*3-1), radius*3,
                                    fill=outline if border else fill)
            if border:
                brush.rounded_rectangle((border*3, border*3, (size-border)*3-1, (size-border)*3-1),
                                        max(0, radius-border)*3, fill=fill)
            corner = corner.resize((size, size), Image.Resampling.LANCZOS)
            for left, top, source in ((0,0,(0,0,extent,extent)),
                                     (width-extent,0,(extent,0,size,extent)),
                                     (0,height-extent,(0,extent,extent,size)),
                                     (width-extent,height-extent,(extent,extent,size,size))):
                image.paste(corner.crop(source), (left,top))
        result = ImageTk.PhotoImage(image, master=self.root)
        self.images[key] = result
        self.bytes += width*height*3
        self.builds += 1
        while self.bytes > 24*1024*1024 and len(self.images) > 1:
            old, _ = self.images.popitem(last=False)
            self.bytes -= old[0]*old[1]*3
        return result


class StaticBoxEngine:
    """Keep CTk layout/input while replacing its decorative vector renderer."""
    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def draw_rounded_rect_with_border(self, *args, **kwargs):
        return False


def paint_skin(widget):
    canvas = widget._canvas
    root = widget._root()
    width = max(1, round(widget._apply_widget_scaling(widget._current_width)))
    height = max(1, round(widget._apply_widget_scaling(widget._current_height)))
    radius = min(width//2, height//2, round(widget._apply_widget_scaling(widget._corner_radius)))
    border = round(widget._apply_widget_scaling(getattr(widget, '_border_width', 0)))
    background = widget._apply_appearance_mode(widget._bg_color)
    fill = widget._apply_appearance_mode(widget._fg_color)
    if fill == 'transparent':
        fill = background
    if getattr(widget, '_skin_hover', False) and getattr(widget, '_state', 'normal') != 'disabled':
        fill = widget._apply_appearance_mode(widget._hover_color)
    outline = widget._apply_appearance_mode(getattr(widget, '_border_color', fill))
    background, fill, outline = (tuple(channel//257 for channel in widget.winfo_rgb(color))
                                 for color in (background, fill, outline))
    key = (width,height,radius,border,background,fill,outline)
    if radius == 0 and border == 0:
        color = '#%02x%02x%02x' % fill
        if canvas.cget('bg') != color:
            canvas.configure(bg=color)
        widget._skin_key = key
        return
    if key == getattr(widget, '_skin_key', None):
        return
    widget._skin_key = key
    if not hasattr(root, '_skin_cache'):
        root._skin_cache = SkinCache(root)
    widget._skin_image = root._skin_cache.get(key)
    if not hasattr(widget, '_skin_item'):
        widget._skin_item = canvas.create_image(0,0,anchor='nw',image=widget._skin_image, tags='static_skin')
    else:
        canvas.itemconfigure(widget._skin_item, image=widget._skin_image)
    canvas.tag_lower('static_skin')
    if getattr(widget, '_skin_hover', False):
        for name in ('_text_label', '_image_label'):
            label = getattr(widget, name, None)
            if label is not None:
                label.configure(bg='#%02x%02x%02x' % fill)
