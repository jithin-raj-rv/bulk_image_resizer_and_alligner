from rembg import remove, new_session
from PIL import Image

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = new_session("u2net")  # lighter default model (~176MB)
    return _session


def remove_background(img: Image.Image) -> Image.Image:
    out = remove(img, session=_get_session())
    if out.mode != "RGBA":
        out = out.convert("RGBA")
    return out


def has_foreground(img: Image.Image, threshold: int = 10) -> bool:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.getchannel("A")
    hist = alpha.histogram()
    transparent = sum(hist[:threshold])
    total = img.width * img.height
    return (total - transparent) > threshold
