from __future__ import annotations

from typing import Callable, Optional

from rembg import remove, new_session
from PIL import Image

from app.core.model_loader import download_model, is_model_downloaded

_session = None

# Callback type aliases (re-exported for convenience)
ProgressCallback = Callable[[int, int], None]          # (bytes_read, total)
StatusCallback = Callable[[str], None]


def _get_session():
    global _session
    if _session is None:
        _session = new_session("u2net")  # lighter default model (~176MB)
    return _session


def ensure_model_ready(
    progress_cb: Optional[ProgressCallback] = None,
    status_cb: Optional[StatusCallback] = None,
) -> object:
    """Ensure the u2net model is downloaded **and** the ONNX session initialized.

    This is the single entry point for first-startup model preparation in the
    GUI.  It performs two phases:

    1. *Download* — if the model file is not yet cached, download it from the
       rembg GitHub release using ``urllib`` so that byte-level progress can be
       reported via *progress_cb*.
    2. *Session init* — create (or reuse) the ONNX inference session.

    Parameters
    ----------
        progress_cb:
            Called as ``progress_cb(bytes_read, total_bytes)`` during download.
        status_cb:
            Called with human-readable status strings.

    Returns
    -------
    object
        The cached ``BaseSession`` instance on success.

    Raises
    ------
    RuntimeError
        On download failure, checksum mismatch, or session initialization error.
    """
    global _session

    # Phase 1 — download (skipped if already cached).
    if not is_model_downloaded():
        download_model(progress_cb=progress_cb, status_cb=status_cb)

    # Phase 2 — create the ONNX session.
    if status_cb:
        status_cb("Initializing model...")
    if _session is None:
        _session = new_session("u2net")
    if status_cb:
        status_cb("Model ready.")

    return _session


def remove_background(
    img: Image.Image,
    hard_alpha: bool = True,
    alpha_threshold: int = 200,
) -> Image.Image:
    """Remove background and optionally collapse semi-transparent alpha edges
    to hard (0 / 255) alpha.

    rembg's u2net model emits a soft alpha matte with edge pixels whose alpha
    is between 0 and 255. When that soft matte is composited onto a fill
    canvas (aligner.paste with mask=product), those edge pixels blend the
    subject colour with the fill colour, producing a visible grey/dark halo
    around the object. Thresholding alpha removes the mid-range pixels so the
    paste composites with no blending, eliminating the grey border.

    Parameters
    ----------
    img:
        Source RGBA/RGB image.
    hard_alpha:
        When True, threshold the alpha channel so every pixel is either fully
        opaque or fully transparent. When False, the soft alpha matte from
        rembg is preserved (anti-aliased edges, but possible grey halo).
    alpha_threshold:
        Alpha values >= this become 255; below this become 0. Only used when
        ``hard_alpha`` is True.
    """
    out = remove(img, session=_get_session())
    if out.mode != "RGBA":
        out = out.convert("RGBA")
    if hard_alpha:
        r, g, b, a = out.split()
        a = a.point(lambda p: 255 if p >= alpha_threshold else 0)
        out = Image.merge("RGBA", (r, g, b, a))
    return out


def has_foreground(img: Image.Image, threshold: int = 10) -> bool:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.getchannel("A")
    hist = alpha.histogram()
    transparent = sum(hist[:threshold])
    total = img.width * img.height
    return (total - transparent) > threshold
