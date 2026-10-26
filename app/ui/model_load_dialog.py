# -*- coding: utf-8 -*-
"""First-run model download / session initialization dialog.

Shows a modal dialog while the u2net model is being downloaded and the ONNX
session is being created.  The heavy work runs in a background ``QThread`` so
the progress bar stays responsive.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QObject,
    Qt,
    QThread,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


class ModelLoaderSignals(QObject):
    """Signal bundle emitted by :class:`ModelLoaderWorker`."""

    progress = pyqtSignal(int, int)          # (bytes_read, total_bytes)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)         # (success, error_message)


class ModelLoaderWorker(QObject):
    """Background worker that downloads the model and initializes the session.

    Lives in its own ``QThread`` so the modal dialog remains responsive.
    Connect to ``self.signals`` to receive progress / status updates.
    """


    def __init__(self) -> None:
        super().__init__()
        self.signals = ModelLoaderSignals()

    def run(self) -> None:
        """Entry point — called when the thread starts."""
        try:
            # Local import to avoid importing rembg at module-load time
            # (keeps the dialog importable without heavy deps).
            from app.core.bg_remover import ensure_model_ready

            ensure_model_ready(
                progress_cb=lambda rb, tb: self.signals.progress.emit(rb, tb),
                status_cb=lambda msg: self.signals.status.emit(msg),
            )
            self.signals.finished.emit(True, "")
        except Exception as exc:  # noqa: BLE001
            self.signals.finished.emit(False, str(exc))


class ModelLoadDialog(QDialog):
    """Modal dialog shown during first-startup model preparation.

    Layout: title, status label, progress bar, byte-count label.
    """

    def __init__(self, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preparing Background Removal Model")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # Dialog flags — title bar only, no maximize/minimize.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.MsWindowsFixedSizeDialogHint
        )
        self.setMinimumWidth(420)
        self._download_complete = False

        # --- layout -------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self._title = QLabel("Bulk Image Resizer &amp; Background Remover")
        self._title.setStyleSheet(
            "font-weight: bold; font-size: 15px; color: #2d2d2d;"
        )
        layout.addWidget(self._title)

        self._status_label = QLabel("Preparing…")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(20)
        layout.addWidget(self._progress_bar)

        self._size_label = QLabel("")
        self._size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._size_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._size_label)

    # ------------------------------------------------------------------
    # Public slots — called from the worker thread via Qt signals
    # ------------------------------------------------------------------
    def set_status(self, text: str) -> None:
        """Update the status label."""
        self._status_label.setText(text)

        # Once download finishes, session init begins — switch to busy.
        if self._download_complete and self._progress_bar.maximum() != 0:
            self._progress_bar.setRange(0, 0)

    def set_progress_bytes(self, read_bytes: int, total_bytes: int) -> None:
        """Update the progress bar and size label with byte counts."""
        self._progress_bar.setRange(0, 100)

        if total_bytes > 0:
            pct = int(read_bytes / total_bytes * 100)
            self._progress_bar.setValue(pct)
            mb_read = read_bytes / (1024 * 1024)
            mb_total = total_bytes / (1024 * 1024)
            self._size_label.setText(f"{mb_read:.1f} MB / {mb_total:.1f} MB")
            if read_bytes >= total_bytes:
                self._download_complete = True
        else:
            # Indeterminate — server didn't send Content-Length.
            self._progress_bar.setRange(0, 0)
            mb_read = read_bytes / (1024 * 1024)
            self._size_label.setText(f"{mb_read:.1f} MB downloaded")

    # ------------------------------------------------------------------
    # Convenience factory — wires up worker + thread in one call
    # ------------------------------------------------------------------
    @staticmethod
    def start_worker(
        parent_dialog: "ModelLoadDialog",
    ) -> tuple[ModelLoaderWorker, QThread]:
        """Create a ``ModelLoaderWorker`` on its own ``QThread`` and connect
        signals to *parent_dialog*.

        Returns ``(worker, thread)``.  The caller should ``thread.start()``
        and, after ``dialog.exec()``, call ``thread.quit()`` / ``thread.wait()``.
        """
        worker = ModelLoaderWorker()
        thread = QThread()
        worker.moveToThread(thread)
        worker.signals.progress.connect(parent_dialog.set_progress_bytes)
        worker.signals.status.connect(parent_dialog.set_status)
        worker.signals.finished.connect(
            lambda ok, err: (
                parent_dialog.accept() if ok else parent_dialog.reject()
            )
        )
        return worker, thread