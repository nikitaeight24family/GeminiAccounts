"""Omni's original orbit mark, shared by the interface and executable icon."""
import math
from PIL import Image, ImageDraw


def omni_icon(size=256):
    canvas = Image.new('RGBA', (1024, 1024))
    draw = ImageDraw.Draw(canvas)
    for start, color in ((-90, '#739aff'), (30, '#66d7b0'), (150, '#a78bfa')):
        draw.arc((148, 148, 876, 876), start=start, end=start + 98, fill=color, width=100)
        for angle in (start, start + 98):
            radians = math.radians(angle)
            x, y = 512 + 364 * math.cos(radians), 512 + 364 * math.sin(radians)
            draw.ellipse((x - 50, y - 50, x + 50, y + 50), fill=color)
        x, y = 512 + 364 * math.cos(math.radians(start)), 512 + 364 * math.sin(math.radians(start))
        draw.ellipse((x - 72, y - 72, x + 72, y + 72), fill=color)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)
