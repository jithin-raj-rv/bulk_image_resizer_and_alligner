import argparse
import os
import sys
from PIL import Image
from app.core.bg_remover import remove_background, has_foreground
from app.core.aligner import Margins, align


def process_one(path, out_dir, canvas_w, canvas_h, margins, anchor, fill, fmt):
    img = Image.open(path).convert("RGBA")
    fg = remove_background(img)
    if not has_foreground(fg):
        print(f"  skip (no foreground): {path}")
        return False
    canvas = align(fg, canvas_w, canvas_h, margins, anchor, fill)
    stem = os.path.splitext(os.path.basename(path))[0]
    ext = "png" if fmt == "png" else "jpg"
    out_path = os.path.join(out_dir, f"{stem}_processed.{ext}")
    if fmt == "jpg":
        canvas = canvas.convert("RGB")
    canvas.save(out_path)
    print(f"  saved: {out_path}")
    return True


def main():
    p = argparse.ArgumentParser(description="Bulk BG remove + resize + align")
    p.add_argument("input", help="input folder")
    p.add_argument("-o", "--output", default=None, help="output folder")
    p.add_argument("--w", type=int, default=1000, help="canvas width")
    p.add_argument("--h", type=int, default=1000, help="canvas height")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--bottom", type=int, default=50)
    p.add_argument("--left", type=int, default=50)
    p.add_argument("--right", type=int, default=50)
    p.add_argument("--anchor", default="center",
                   choices=["center", "left-center", "right-center"])
    p.add_argument("--fill", default="transparent", help="transparent or R,G,B e.g. 255,255,255")
    p.add_argument("--fmt", default="png", choices=["png", "jpg"])
    args = p.parse_args()

    in_dir = args.input
    out_dir = args.output or os.path.join(in_dir, "processed")
    os.makedirs(out_dir, exist_ok=True)

    if args.fill == "transparent":
        fill = (0, 0, 0, 0)
    else:
        r, g, b = [int(x) for x in args.fill.split(",")]
        fill = (r, g, b, 255)

    margins = Margins(top=args.top, bottom=args.bottom, left=args.left, right=args.right)

    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = [os.path.join(in_dir, f) for f in os.listdir(in_dir)
             if f.lower().endswith(exts)]
    print(f"Found {len(files)} images. Processing...")
    ok = 0
    for f in files:
        try:
            if process_one(f, out_dir, args.w, args.h, margins, args.anchor, fill, args.fmt):
                ok += 1
        except Exception as e:
            print(f"  ERROR {f}: {e}")
    print(f"Done. {ok}/{len(files)} processed. Output: {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        from app.ui.main_window import main as gui_main
        gui_main()
    else:
        main()
