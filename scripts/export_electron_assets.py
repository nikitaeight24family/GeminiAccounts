"""Export the existing Omni UI artwork unchanged; never instantiate a Tk window."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App, TEXT
from omni_brand import omni_icon
from PIL import Image, ImageDraw

def main():
    target = Path(__file__).resolve().parents[1] / 'electron' / 'renderer' / 'assets'
    target.mkdir(parents=True, exist_ok=True)
    omni_icon().save(target / 'omni.png')
    for name, image in App.make_provider_icons().items():
        image.cget('dark_image').save(target / (name+'.png'))
        image.cget('light_image').save(target / (name+'-light.png'))
    for name, image in App.make_playback_icons().items():
        if isinstance(image, list):
            continue
        name = 'play' if name is True else 'pause' if name is False else name
        image.cget('dark_image').save(target / (name+'.png'))
        image.cget('light_image').save(target / (name+'-light.png'))
    for hidden in (False, True):
        image = Image.new('RGBA', (64,64))
        draw = ImageDraw.Draw(image)
        if hidden:
            draw.arc((5,7,59,41),0,180,fill=TEXT,width=5)
            for lash in ((15,35,10,43),(32,41,32,51),(49,35,54,43)):
                draw.line(lash,fill=TEXT,width=4)
        else:
            draw.ellipse((5,17,59,47),outline=TEXT,width=5)
            draw.ellipse((23,23,41,41),fill=TEXT)
        image.save(target / ('eye-closed.png' if hidden else 'eye-open.png'))
    image = Image.new('RGBA',(64,64))
    draw = ImageDraw.Draw(image)
    draw.line((20,20,44,44),fill=TEXT,width=4)
    draw.line((20,44,44,20),fill=TEXT,width=4)
    image.save(target/'remove.png')

if __name__ == '__main__':
    main()
