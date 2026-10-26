# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Bulk Image Resizer & BG Remover
#
# Usage:
#   python -m PyInstaller --clean --noconfirm bulk_image_resizer.spec
#
# Output:
#   dist/bulk_image_resizer.exe  (single self-contained executable)
#
# Notes:
#   - This spec produces a ONE-FILE executable (no COLLECT step).
#     To switch to one-folder mode, uncomment the COLLECT block below.
#   - console=False => windowed mode (no console popup for GUI mode).
#   - The u2net model (~176 MB) is downloaded automatically on first run
#     into ~/.rembg/models.  A modal progress dialog is shown during the
#     download and ONNX session initialization.  The model is NOT bundled
#     in the EXE to keep the package small.  For truly offline/portable
#     use, pre-download the model once and distribute the ~/.rembg/models
#     folder alongside.
#   - Package metadata (.dist-info) for pymatting, rembg, etc. is
#     dynamically collected so that importlib.metadata.version() calls
#     at import time do not crash with PackageNotFoundError.

import os as _os
import importlib.metadata as _ilmd

block_cipher = None

# ---------------------------------------------------------------------------
# Collect .dist-info directories for packages that call
# importlib.metadata.version() at import time (e.g. pymatting.__init__).
# Without these, the frozen EXE raises PackageNotFoundError.
# ---------------------------------------------------------------------------
_metadata_datas = []
for _pkg_name in ("pymatting", "rembg", "pooch", "scikit-image", "onnxruntime"):
    try:
        _dist = _ilmd.distribution(_pkg_name)
        _meta_path = str(_dist._path)
        if _os.path.isdir(_meta_path):
            _metadata_datas.append((_meta_path, _os.path.basename(_meta_path)))
    except Exception:
        pass

a = Analysis(
    ["main.py"],
    # Ensure the 'app' package directory is discoverable at import time
    pathex=["."],
    # Bundle the entire app/ package + package metadata
    datas=[("app", "app")] + _metadata_datas,
    binaries=[],
    # rembg relies on dynamic imports and optional backends
    hiddenimports=[
        # pymatting is imported by rembg.bg and calls
        # importlib.metadata.version("pymatting") at import time
        "pymatting",
        # rembg core + sessions
        "rembg",
        "rembg.session_factory",
        "rembg.sessions",
        # onnxruntime backend
        "onnxruntime",
        "onnxruntime.capi",
        "onnxruntime.capi.onnxruntime_pybind11_state",
        # image / scientific stack
        "numpy",
        "scipy",
        "scipy.ndimage",
        "scipy.special",
        "skimage",
        "skimage.color",
        "skimage.transform",
        "skimage.measure",
        "skimage.morphology",
        # misc utilities used by rembg
        "tqdm",
        "pooch",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bulk_image_resizer",
    debug="no",
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    # console=False => windowed (no console popup for GUI mode)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# -------------------------------------------------------------------
# One-folder mode (optional): uncomment this block to produce a folder
#   containing bulk_image_resizer.exe plus all dependency DLLs and data.
# -------------------------------------------------------------------
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.datas,
#     strip=False,
#     upx=True,
#     name="bulk_image_resizer",
# )
