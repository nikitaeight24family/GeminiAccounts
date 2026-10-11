"""Compact quota indicators shared by collapsed sections."""
import math
from PIL import Image, ImageDraw, ImageFont


def quota_level(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return None, '#8390a3'
    value = min(1, max(0, value))
    return value, '#36bb87' if value >= .5 else '#edaa43' if value > .1 else '#f06472'


def quota_dot(value, light=False, label=''):
    value, color = quota_level(value)
    image = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(image)
    bounds = (5, 5, 59, 59)
    draw.ellipse(bounds, fill='#d5dfed' if light else '#354157')
    if value is not None and value > 0:
        draw.pieslice(bounds, start=-90, end=-90 + 360 * value, fill=color)
    draw.ellipse(bounds, outline=color, width=4)
    if label:
        draw.text((32, 33), label, font=ImageFont.load_default(size=23), anchor='mm',
                  fill='#ffffff', stroke_width=2, stroke_fill='#243047')
    elif value is None:
        draw.line((23, 32, 41, 32), fill=color, width=4)
    return image
