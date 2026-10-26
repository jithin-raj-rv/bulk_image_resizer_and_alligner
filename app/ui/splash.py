# -*- coding: utf-8 -*-
"""Minimal startup splash screen shown before the heavy UI modules are imported.

Only PyQt6 is imported here so the splash can appear as early as possible
after the PyInstaller bootloader finishes extracting the one-file bundle.
Without this, a frozen ``--windowed`` one-file EXE shows nothing while it
extracts its bundle to ``_MEIxxxx`` and imports PyQt6/rembg/onnxruntime, which
can take a minute on first launch.
"""
from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSplashScreen


def _resource_path(relative_path: str) -> str:
    """Absolute path to a bundled resource (dev mode and PyInstaller _MEIPASS)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def show_splash(app, message: str = "Loading…") -> QSplashScreen:
    """Show a frameless splash screen and return it.

    The caller keeps the returned splash alive and calls ``splash.close()``
    (or ``splash.finish(main_window)``) once the main window is ready to show.
    """
    splash = QSplashScreen()
    splash.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
    )

    try:
        pix = QPixmap(_resource_path("logo.png"))
        if not pix.isNull():
            splash.setPixmap(pix)
    except Exception:
        pass

    splash.showMessage(
        message,
        int(
            Qt.AlignmentFlag.AlignBottom
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignAbsolute
        ),
        Qt.GlobalColor.white,
    )
    splash.show()
    app.processEvents()
    return splash
