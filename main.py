import argparse
import os
import sys
from PIL import Image
from app.core.bg_remover import remove_background, has_foreground
from app.core.aligner import Margins, align


def _resolve_out_path(out_path, policy):
    """Handle an existing output file. Returns (final_path, action).
    action in {"ok", "overwritten", "renamed", "skipped_exists"}.
    CLI is non-interactive, so "ask" behaves like "overwrite".
    """
    if not os.path.exists(out_path):
        return out_path, "ok"
    if policy == "skip":
        return out_path, "skipped_exists"
    if policy == "overwrite":
        return out_path, "overwritten"
    if policy == "rename":
        stem, ext = os.path.splitext(out_path)
        counter = 2
        candidate = f"{stem}_{counter}{ext}"
        while os.path.exists(candidate):
            counter += 1
            candidate = f"{stem}_{counter}{ext}"
        return candidate, "renamed"
    # "ask" -> overwrite (cannot prompt in CLI)
    return out_path, "overwritten"


def process_one(path, out_dir, canvas_w, canvas_h, margins, anchor, fill, fmt,
                conflict_policy="overwrite", max_retries=3, retry_delay=1.5,
                hard_alpha=True, alpha_threshold=200):
    import time

    # --- open source image (may be locked by another app) ---
    img = None
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            img = Image.open(path).convert("RGBA")
            break
        except (OSError, PermissionError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(retry_delay)
    if img is None:
        print(f"  ERROR (file locked) {path}: {last_err}")
        return "failed"

    try:
        fg = remove_background(img, hard_alpha=hard_alpha,
                               alpha_threshold=alpha_threshold)
        if not has_foreground(fg):
            print(f"  skip (no foreground): {path}")
            return "skipped_no_fg"

        canvas = align(fg, canvas_w, canvas_h, margins, anchor, fill)
        stem = os.path.splitext(os.path.basename(path))[0]
        ext = "png" if fmt == "png" else "jpg"
        out_path = os.path.join(out_dir, f"{stem}_processed.{ext}")
        if fmt == "jpg":
            canvas = canvas.convert("RGB")

        # --- resolve existing-file conflict ---
        final_path, action = _resolve_out_path(out_path, conflict_policy)
        if action == "skipped_exists":
            print(f"  skip (exists): {os.path.basename(out_path)}")
            return "skipped_exists"

        # --- save destination (may be locked by another app) ---
        saved = False
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                canvas.save(final_path)
                saved = True
                break
            except (OSError, PermissionError) as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(retry_delay)
        if not saved:
            print(f"  ERROR (file locked) {final_path}: {last_err}")
            return "failed"

        if action == "overwritten":
            print(f"  overwritten: {final_path}")
        elif action == "renamed":
            print(f"  renamed: {final_path}")
        else:
            print(f"  saved: {final_path}")
        return action
    finally:
        img.close()


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
    p.add_argument("--conflict-policy", default="overwrite",
                   choices=["overwrite", "skip", "rename", "ask"],
                   help="What to do when the output file already exists "
                        "(default: overwrite). CLI is non-interactive, so "
                        "'ask' behaves like 'overwrite'.")
    p.add_argument("--max-retries", type=int, default=3,
                   help="Retries when a file is locked by another app (default: 3).")
    p.add_argument("--hard-alpha", action="store_true", default=True,
                   help="Threshold alpha to hard edges (0/255) to remove grey border (default: enabled).")
    p.add_argument("--no-hard-alpha", action="store_false", dest="hard_alpha",
                   help="Preserve soft alpha matte from rembg (anti-aliased edges, possible grey halo).")
    p.add_argument("--alpha-threshold", type=int, default=200,
                   help="Alpha >= threshold becomes opaque; below becomes transparent (default: 200).")
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
    stats = {"ok": 0, "overwritten": 0, "renamed": 0,
             "skipped_no_fg": 0, "skipped_exists": 0, "failed": 0}
    for f in files:
        try:
            result = process_one(f, out_dir, args.w, args.h, margins,
                                 args.anchor, fill, args.fmt,
                                 conflict_policy=args.conflict_policy,
                                 max_retries=args.max_retries,
                                 hard_alpha=args.hard_alpha,
                                 alpha_threshold=args.alpha_threshold)
            stats[result] = stats.get(result, 0) + 1
        except Exception as e:
            print(f"  ERROR {f}: {e}")
            stats["failed"] = stats.get("failed", 0) + 1
    print("Done.")
    print(f"  processed        : {stats['ok']}")
    print(f"  overwritten      : {stats['overwritten']}")
    print(f"  renamed          : {stats['renamed']}")
    print(f"  skipped (no fg)  : {stats['skipped_no_fg']}")
    print(f"  skipped (exists) : {stats['skipped_exists']}")
    print(f"  failed           : {stats['failed']}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # GUI mode: use tkinter (stdlib, loads instantly) for the splash
        # screen.  PyQt6 itself is part of the slow import chain, so a
        # PyQt6 splash can't render during the heavy import.  tkinter has
        # no heavy deps and shows immediately.
        import tkinter as tk

        # --- Show tkinter splash immediately (no heavy imports) ---
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        # Try to show logo.png if it exists next to the script / in bundle
        import os
        logo_path = None
        # Check common locations
        for candidate in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "logo.png"),
            "logo.png",
        ]:
            if candidate and os.path.isfile(candidate):
                logo_path = candidate
                break

        width, height = 400, 200
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.configure(bg="#1e1e2e")

        try:
            if logo_path:
                from tkinter import PhotoImage
                img = PhotoImage(file=logo_path)
                # Scale if too big
                lbl_img = tk.Label(root, image=img, bg="#1e1e2e")
                lbl_img.image = img
                lbl_img.pack(pady=10)
        except Exception:
            pass

        lbl_text = tk.Label(
            root,
            text="Loading Bulk Image Resizer & Background Remover…",
            fg="white",
            bg="#1e1e2e",
            font=("Segoe UI", 11),
        )
        lbl_text.pack(pady=10)

        # Force render before heavy import blocks
        root.update()
        root.update_idletasks()

        try:
            # --- Heavy import happens here (splash is visible) ---
            from PyQt6.QtWidgets import QApplication, QMessageBox
            from app.ui.main_window import create_main_window

            app = QApplication(sys.argv)

            # Dismiss tkinter splash
            root.destroy()

            # Show PyQt6 model-load dialog + main window
            create_main_window(app=app, splash=None)
            import sys as _sys
            _sys.exit(app.exec())
        except Exception as exc:  # noqa: BLE001
            try:
                root.destroy()
            except Exception:
                pass
            try:
                from PyQt6.QtWidgets import QApplication, QMessageBox
                app = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()
            except Exception:
                app = None
            if app:
                QMessageBox.critical(
                    None,
                    "Startup Error",
                    f"The application failed to start:\n\n{exc}",
                )
            else:
                print(f"Startup Error: {exc}")
            sys.exit(1)
    else:
        main()
