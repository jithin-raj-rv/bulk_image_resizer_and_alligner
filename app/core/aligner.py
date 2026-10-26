from dataclasses import dataclass
from PIL import Image


@dataclass
class Margins:
    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


def safe_area(canvas_w: int, canvas_h: int, m: Margins):
    return canvas_w - m.left - m.right, canvas_h - m.top - m.bottom


def align(product, canvas_w, canvas_h, m, anchor="center", fill=(255, 255, 255, 0)):
    """Crop product to its non-transparent bbox, then scale to fit safe area and paste."""
    if product.mode != "RGBA":
        product = product.convert("RGBA")
    bbox = product.getbbox()
    if bbox:
        product = product.crop(bbox)
    sw, sh = safe_area(canvas_w, canvas_h, m)
    if sw <= 0 or sh <= 0:
        raise ValueError("Margins too large for canvas")
    scale = min(sw / product.width, sh / product.height)
    new_w = max(1, int(product.width * scale))
    new_h = max(1, int(product.height * scale))
    product = product.resize((new_w, new_h), Image.LANCZOS)

    if anchor == "center":
        ox = (sw - new_w) // 2
        oy = (sh - new_h) // 2
    elif anchor == "left-center":
        ox = 0
        oy = (sh - new_h) // 2
    elif anchor == "right-center":
        ox = sw - new_w
        oy = (sh - new_h) // 2
    else:
        ox = (sw - new_w) // 2
        oy = (sh - new_h) // 2

    canvas = Image.new("RGBA", (canvas_w, canvas_h), fill)
    canvas.paste(product, (m.left + ox, m.top + oy), product)
    return canvas
