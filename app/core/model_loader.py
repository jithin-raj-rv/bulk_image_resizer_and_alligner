# -*- coding: utf-8 -*-
"""Model download and cache management for the u2net background-removal model.

rembg normally downloads its ~176 MB ONNX model lazily via *pooch* with a
stderr-based progress bar that is invisible in a ``--windowed`` GUI application.
This module provides a plain-urllib download path with byte-level progress
callbacks and MD5 verification so the UI layer can present a native
``QProgressDialog`` to the user.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Model metadata (mirrors rembg.sessions.u2net.U2netSession)
# ---------------------------------------------------------------------------
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
MODEL_MD5 = "60024c5c889badc19c04ad937298a77b"
MODEL_FILE_NAME = "u2net.onnx"

ProgressCallback = Callable[[int, int], None]          # (bytes_read, total_bytes)
StatusCallback = Callable[[str], None]


def _get_rembg_home() -> str:
    """Return the rembg home directory (``~/.rembg`` by default)."""
    u2net_home = os.getenv("U2NET_HOME")
    if u2net_home:
        return os.path.expanduser(u2net_home)
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, "rembg")
    return os.path.expanduser(os.getenv("REMBG_HOME", os.path.join("~", ".rembg")))


def get_model_dir() -> str:
    """Return the directory where rembg stores the u2net model.

    Mirrors ``BaseSession.model_dir`` → ``$REMBG_HOME/models/u2net``.
    """
    return os.path.join(_get_rembg_home(), "models", "u2net")


def get_model_path() -> str:
    """Return the full filesystem path to the cached ``.onnx`` model."""
    return os.path.join(get_model_dir(), MODEL_FILE_NAME)


def _get_legacy_path() -> str:
    """Legacy location: ``$U2NET_HOME/u2net.onnx`` (pre-1.x layout)."""
    home = os.getenv("U2NET_HOME")
    if home:
        return os.path.join(os.path.expanduser(home), MODEL_FILE_NAME)
    return os.path.expanduser(os.path.join("~", ".u2net", MODEL_FILE_NAME))


def _is_valid_model(path: str) -> bool:
    """Validate the MD5 checksum of a model file."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(262_144), b""):
                h.update(chunk)
        return h.hexdigest() == MODEL_MD5
    except OSError:
        return False


def resolve_existing_model_path() -> Optional[str]:
    """Find an existing valid model file, checking new + legacy paths."""
    for path in (get_model_path(), _get_legacy_path()):
        if os.path.isfile(path) and _is_valid_model(path):
            return path
    return None


def is_model_downloaded() -> bool:
    """Return ``True`` if a valid model file already exists in the cache."""
    return resolve_existing_model_path() is not None


def download_model(
    progress_cb: Optional[ProgressCallback] = None,
    status_cb: Optional[StatusCallback] = None,
) -> str:
    """Download the u2net model with optional progress/status reporting.

    Parameters
    ----------
    progress_cb:
        Called as ``progress_cb(bytes_read, total_bytes)`` roughly every 64 KB.
    status_cb:
        Called with human-readable status messages.

    Returns
    -------
    str
        The path to the (now valid) model file.

    Raises
    ------
    RuntimeError
        On network failure, I/O error, or MD5 checksum mismatch.
    """
    model_path = get_model_path()

    # Already valid → nothing to do.
    if os.path.isfile(model_path) and _is_valid_model(model_path):
        return model_path

    # Stale / corrupt file → remove so download restarts cleanly.
    if os.path.isfile(model_path):
        if status_cb:
            status_cb("Removing corrupted model cache...")
        os.remove(model_path)

    model_dir = get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    tmp_path = model_path + ".download"

    if status_cb:
        status_cb("Downloading background-removal model...")

    try:
        req = urllib.request.Request(
            MODEL_URL,
            headers={"User-Agent": "BulkImageResizer/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("content-length", 0)) or 0
            read = 0
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = resp.read(65_536)  # 64 KB
                    if not chunk:
                        break
                    out.write(chunk)
                    read += len(chunk)
                    if progress_cb:
                        progress_cb(read, total)
    except Exception as exc:  # noqa: BLE001 -- surface any error to caller
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(f"Failed to download model: {exc}") from exc

    # Atomic rename to final location.
    os.replace(tmp_path, model_path)

    # Verify checksum.
    if status_cb:
        status_cb("Verifying model integrity...")
    if not _is_valid_model(model_path):
        os.remove(model_path)
        raise RuntimeError(
            "Model download verification failed (MD5 checksum mismatch)."
        )

    return model_path