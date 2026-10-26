import os, sys, threading, gc
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QSpinBox, QComboBox, QFileDialog, QProgressBar,
    QMessageBox, QFrame, QListWidget, QListWidgetItem, QAbstractItemView, QListView, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PIL import Image, ImageDraw
from app.core.bg_remover import remove_background, has_foreground
from app.core.aligner import Margins, align


class PreviewSignals(QObject):
    done = pyqtSignal(object)

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class ProcessWorker(threading.Thread):
    def __init__(self, files, out_dir, canvas_w, canvas_h, margins, anchor, fill, fmt, signals, settings_map=None, fg_map=None, overwrite_existing=True):
        super().__init__(daemon=True)
        self.files = files
        self.out_dir = out_dir
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.margins = margins
        self.anchor = anchor
        self.fill = fill
        self.fmt = fmt
        self.signals = signals
        self.cancel = False
        self.settings_map = settings_map or {}
        self.fg_map = fg_map or {}
        self.overwrite_existing = overwrite_existing

    def run(self):
        os.makedirs(self.out_dir, exist_ok=True)
        total = len(self.files)
        for i, f in enumerate(self.files):
            if self.cancel:
                self.signals.status.emit("Cancelled")
                break
            self.signals.status.emit(f"Processing {os.path.basename(f)}")
            try:
                s_per = self.settings_map.get(f, {})
                bg_mode = s_per.get("bg_mode", "Remove background")
                img = None
                # Use cached foreground (edited preview) when available so
                # re-processing after edits exports the edited image.
                fg = self.fg_map.get(f)
                if fg is not None:
                    fg = fg.copy()
                else:
                    img = Image.open(f).convert("RGBA")
                    if bg_mode == "Keep original":
                        fg = img.copy()
                    else:
                        fg = remove_background(img)
                if not has_foreground(fg):
                    self.signals.status.emit(f"skip (no foreground): {os.path.basename(f)}")
                else:
                    s = self.settings_map.get(f, {})
                    cw = s.get("w", self.canvas_w)
                    ch = s.get("h", self.canvas_h)
                    m = s.get("margins", self.margins)
                    anc = s.get("anchor", self.anchor)
                    fl = s.get("fill", self.fill)
                    canvas = align(fg, cw, ch, m, anc, fl)
                    stem = os.path.splitext(os.path.basename(f))[0]
                    ext = "png" if self.fmt == "png" else "jpg"
                    out_path = os.path.join(self.out_dir, f"{stem}_processed.{ext}")
                    if self.fmt == "jpg":
                        canvas = canvas.convert("RGB")
                    existed = os.path.exists(out_path)
                    if existed and not self.overwrite_existing:
                        self.signals.status.emit(f"skip (exists): {os.path.basename(out_path)}")
                    else:
                        canvas.save(out_path)
                        note = "overwritten" if existed else "done"
                        self.signals.status.emit(f"{note}: {os.path.basename(out_path)}")
                del img, fg
                gc.collect()
            except Exception as e:
                self.signals.error.emit(f"{f}: {e}")
            self.signals.progress.emit(i + 1, total)
        self.signals.finished.emit()


def pil_to_pixmap(img: Image.Image, max_w=260, max_h=260):
    img = img.convert("RGBA")
    img.thumbnail((max_w, max_h))
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bulk Image BG Remover + Resizer + Aligner")
        self.resize(1000, 700)
        self.setMinimumSize(900, 650)
        self.files = []
        self.image_settings = {}
        self.image_fg = {}
        self._current_file = None
        self.out_dir = None
        self.worker = None
        self._processing = False
        self._build()
        self.setAcceptDrops(True)
        self.prev_signals = PreviewSignals()
        self.prev_signals.done.connect(self._on_preview_fg)
        self._model_ready = True  # model preloaded in main() before MainWindow
        self.signals = WorkerSignals()
        self.signals.progress.connect(self.on_progress)
        self.signals.status.connect(self.status_label.setText)
        self.signals.finished.connect(self.on_finished)
        self.signals.error.connect(lambda e: self.status_label.setText(f"ERR: {e}"))

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        ctrl = QVBoxLayout()
        layout.addLayout(ctrl, 1)

        btn_pick = QPushButton("Select Input Folder")
        btn_pick.clicked.connect(self.pick_folder)
        ctrl.addWidget(btn_pick)

        self.file_count = QLabel("No files selected")
        ctrl.addWidget(self.file_count)

        row = QHBoxLayout()
        row.addWidget(QLabel("Canvas W"))
        self.spin_w = QSpinBox(); self.spin_w.setRange(64, 4096); self.spin_w.setValue(1000)
        row.addWidget(self.spin_w)
        row.addWidget(QLabel("H"))
        self.spin_h = QSpinBox(); self.spin_h.setRange(64, 4096); self.spin_h.setValue(1000)
        row.addWidget(self.spin_h)
        self.spin_w.valueChanged.connect(self.update_preview)
        self.spin_h.valueChanged.connect(self.update_preview)
        ctrl.addLayout(row)

        self.sliders = {}
        for name in ("top", "bottom", "left", "right"):
            r = QHBoxLayout()
            r.addWidget(QLabel(name.capitalize()))
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 400)
            s.setValue(50)
            s.valueChanged.connect(self.update_preview)
            self.sliders[name] = s
            r.addWidget(s)
            v = QLabel("50")
            s.valueChanged.connect(lambda val, lbl=v: lbl.setText(str(val)))
            r.addWidget(v)
            ctrl.addLayout(r)

        self.anchor = QComboBox()
        self.anchor.addItems(["center", "left-center", "right-center"])
        self.anchor.currentTextChanged.connect(self.update_preview)
        ctrl.addWidget(QLabel("Anchor"))
        ctrl.addWidget(self.anchor)

        self.fill_combo = QComboBox()
        self.fill_combo.addItems(["transparent", "white", "black"])
        self.fill_combo.currentTextChanged.connect(self.update_preview)
        ctrl.addWidget(QLabel("Background fill"))
        ctrl.addWidget(self.fill_combo)

        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg"])
        ctrl.addWidget(QLabel("Output format"))
        ctrl.addWidget(self.fmt)

        self.bg_mode = QComboBox()
        self.bg_mode.addItems(["Keep original", "Remove background"])
        self.bg_mode.currentTextChanged.connect(self._on_bg_mode_changed)
        ctrl.addWidget(QLabel("Background"))
        ctrl.addWidget(self.bg_mode)

        btn_apply_sel = QPushButton("Apply to selected")
        btn_apply_sel.clicked.connect(self.apply_to_selected)
        ctrl.addWidget(btn_apply_sel)
        btn_apply_all = QPushButton("Apply to all")
        btn_apply_all.clicked.connect(self.apply_to_all)
        ctrl.addWidget(btn_apply_all)

        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self.remove_selected)
        ctrl.addWidget(btn_remove)

        btn_proc = QPushButton("Process All")
        self.btn_proc = btn_proc
        btn_proc.clicked.connect(self.process_all)
        ctrl.addWidget(btn_proc)

        btn_proc_cur = QPushButton("Process Current")
        self.btn_proc_cur = btn_proc_cur
        btn_proc_cur.clicked.connect(self.process_current)
        ctrl.addWidget(btn_proc_cur)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.cancel_proc)
        ctrl.addWidget(btn_cancel)

        self.progress = QProgressBar()
        ctrl.addWidget(self.progress)
        self.status_label = QLabel("Ready")
        ctrl.addWidget(self.status_label)

        right = QVBoxLayout()
        layout.addLayout(right, 1)
        self.preview_before = QLabel("Before")
        self.preview_after = QLabel("After")
        self.preview_before.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_after.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.preview_before)
        right.addWidget(self.preview_after)
        self.gallery = QListWidget()
        self.gallery.setIconSize(QSize(80, 80))
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.gallery.itemClicked.connect(self._on_gallery_click)
        self.gallery.setWordWrap(True)
        self.gallery.setDragEnabled(False)
        self.gallery.setStyleSheet("""
            QListWidget {
                background: #2b2b2b;
                border: 1px solid #444;
                outline: none;
            }
            QListWidget::item {
                background: #333;
                border: 1px solid #444;
                padding: 6px;
                margin: 4px;
                color: #ddd;
            }
            QListWidget::item:selected {
                background: #3d5a80;
                border: 2px solid #98c1d9;
                color: #fff;
            }
            QListWidget::item:hover:!selected {
                background: #3a3a3a;
                border: 1px solid #666;
            }
        """)
        gallery_scroll = QScrollArea()
        gallery_scroll.setWidgetResizable(True)
        gallery_scroll.setWidget(self.gallery)
        gallery_scroll.setMinimumHeight(180)
        right.addWidget(gallery_scroll, 1)

        self._sample_img = None
        self._sample_fg = None

    def pick_folder(self):
        try:
            d = QFileDialog.getExistingDirectory(self, "Select input folder")
            if not d:
                return
            exts = (".jpg", ".jpeg", ".png", ".webp")
            self.files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(exts)]
            self.out_dir = os.path.join(d, "processed")
            self.file_count.setText(f"{len(self.files)} images found")
            if self.files:
                self._sample_img = Image.open(self.files[0]).convert("RGBA")
                self._sample_fg = None
                self._current_file = self.files[0] if self.files else None
                self._populate_gallery()
                self.update_preview()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.status_label.setText(f"err: {e}")

    def _margins(self):
        return Margins(top=self.sliders["top"].value(),
                      bottom=self.sliders["bottom"].value(),
                      left=self.sliders["left"].value(),
                      right=self.sliders["right"].value())

    def _fill(self):
        v = self.fill_combo.currentText()
        if v == "transparent":
            return (0, 0, 0, 0)
        if v == "white":
            return (255, 255, 255, 255)
        return (0, 0, 0, 255)

    def update_preview(self):
        if self._sample_img is None:
            return
        try:
            if self._sample_fg is None:
                self.preview_before.setPixmap(pil_to_pixmap(self._sample_img))
                self.preview_after.setPixmap(pil_to_pixmap(self._sample_img))
                return
            canvas = align(self._sample_fg, self.spin_w.value(), self.spin_h.value(),
                           self._margins(), self.anchor.currentText(), self._fill())
            self.preview_before.setPixmap(pil_to_pixmap(self._sample_img))
            self.preview_after.setPixmap(pil_to_pixmap(canvas))
        except Exception as e:
            self.status_label.setText(f"preview err: {e}")

    def remove_bg_preview(self):
        if self._sample_img is None:
            return
        self.status_label.setText("Removing background (preview)...")
        def worker():
            fg = remove_background(self._sample_img.copy())
            self.prev_signals.done.emit(fg)
        threading.Thread(target=worker, daemon=True).start()

    def _on_preview_fg(self, fg):
        if fg is None:
            self._model_ready = True
            self.status_label.setText("Model ready")
            return
        self._sample_fg = fg
        if self._current_file:
            self.image_fg[self._current_file] = fg
        self.status_label.setText("Preview ready")
        self.update_preview()

    def _on_bg_mode_changed(self, text):
        if self._sample_img is None or not self._current_file:
            return
        # persist bg mode choice per image
        st = self.image_settings.get(self._current_file, {})
        st["bg_mode"] = text
        self.image_settings[self._current_file] = st
        if text == "Remove background":
            self.remove_bg_preview()
        elif text == "Keep original":
            self._sample_fg = self._sample_img.copy()
            self.image_fg[self._current_file] = self._sample_fg
            self.update_preview()
            self.status_label.setText("Background kept")

    def _populate_gallery(self):
        self.gallery.clear()
        for p in self.files:
            name = os.path.basename(p)
            # show a tiny badge if background removal already applied
            if p in self.image_fg:
                name = name + "  [bg removed]"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)  # full path on hover
            # give each item enough room for wrapped text (2–3 lines) beneath the 80px thumb
            item.setSizeHint(QSize(110, 130))
            try:
                pix = QPixmap(p)
                if not pix.isNull():
                    item.setIcon(QIcon(pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            except Exception:
                pass
            self.gallery.addItem(item)

    def _on_gallery_click(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._current_file = p
            self._sample_img = Image.open(p).convert("RGBA")
            self._sample_fg = self.image_fg.get(p)
            # determine bg_mode from saved settings, falling back to fg presence
            st = self.image_settings.get(p, {})
            saved_mode = st.get("bg_mode")
            if saved_mode in ("Keep original", "Remove background"):
                mode = saved_mode
            elif self._sample_fg is not None:
                mode = "Remove background"
            else:
                mode = "Keep original"
            if self.bg_mode.currentText() == mode:
                self._on_bg_mode_changed(mode)
            else:
                self.bg_mode.setCurrentText(mode)
            s = self.image_settings.get(p)
            if s:
                self.spin_w.setValue(s["w"]); self.spin_h.setValue(s["h"])
                self.sliders["top"].setValue(s["margins"].top); self.sliders["bottom"].setValue(s["margins"].bottom)
                self.sliders["left"].setValue(s["margins"].left); self.sliders["right"].setValue(s["margins"].right)
                self.anchor.setCurrentText(s["anchor"])
            self.update_preview()
            self.status_label.setText(f"Selected: {os.path.basename(p)}")
        except Exception as e:
            self.status_label.setText(f"err: {e}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    event.ignore()
                    return
                if not url.toLocalFile():
                    event.ignore()
                    return
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            all_valid = all(url.isLocalFile() and url.toLocalFile() for url in event.mimeData().urls())
            if all_valid:
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        try:
            paths = []
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                p = url.toLocalFile()
                if not p:
                    continue
                if os.path.isdir(p):
                    for root, _, fs in os.walk(p):
                        for f in fs:
                            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
                                paths.append(os.path.join(root, f))
                elif os.path.isfile(p):
                    paths.append(p)
            if paths:
                existing = set(self.files)
                for p in paths:
                    if p not in existing:
                        self.files.append(p)
                self.files = sorted(self.files)
                self._sample_img = Image.open(self.files[0]).convert("RGBA")
                self._sample_fg = None
                self._current_file = self.files[0] if self.files else None
                self._populate_gallery()
                self.status_label.setText(f"Loaded {len(self.files)} images (drag & drop)")
                self.update_preview()
            event.acceptProposedAction()
        except Exception as e:
            self.status_label.setText(f"drop err: {e}")
            event.ignore()

    def _current_settings(self):
        m = Margins(top=self.sliders["top"].value(), bottom=self.sliders["bottom"].value(),
                    left=self.sliders["left"].value(), right=self.sliders["right"].value())
        return {"w": self.spin_w.value(), "h": self.spin_h.value(),
                "margins": m, "anchor": self.anchor.currentText(),
                "fill": self._fill()}

    def apply_to_selected(self):
        try:
            if not self.files:
                self.status_label.setText("No images loaded")
                return
            s = self._current_settings()
            selected = [it.data(Qt.ItemDataRole.UserRole) for it in self.gallery.selectedItems()]
            if not selected:
                if self._current_file:
                    selected = [self._current_file]
                else:
                    selected = [self.files[0]]
            for p in selected:
                self.image_settings[p] = s
            self.status_label.setText(f"Applied settings to {len(selected)} image(s). Tip: Ctrl/Shift-click to multi-select.")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")

    def apply_to_all(self):
        if not self.files:
            QMessageBox.warning(self, "No files", "Select a folder first")
            return
        self.out_dir = os.path.join(os.path.dirname(self.files[0]), "output")
        os.makedirs(self.out_dir, exist_ok=True)
        try:
            s = self._current_settings()
            s["bg_mode"] = self.bg_mode.currentText()
            for p in self.files:
                self.image_settings[p] = s
            self.update_preview()
            self.status_label.setText(f"Applied settings to all {len(self.files)} images")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")
        self.status_label.setText("Applied settings to all images. Use Process All to export.")

    def cancel_proc(self):
        if getattr(self, "worker", None):
            self.worker.cancel = True

    def remove_selected(self):
        if not self.files:
            QMessageBox.warning(self, "No files", "No images to remove")
            return
        selected_items = self.gallery.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No selection", "Select one or more images in the gallery to remove")
            return
        to_remove = [it.data(Qt.ItemDataRole.UserRole) for it in selected_items]
        removed_count = 0
        for p in to_remove:
            if p in self.files:
                self.files.remove(p)
                removed_count += 1
            self.image_settings.pop(p, None)
            self.image_fg.pop(p, None)
        self._populate_gallery()
        if self._current_file in to_remove:
            if self.files:
                self._current_file = self.files[0]
                first_item = self.gallery.item(0)
                if first_item:
                    self.gallery.setCurrentItem(first_item)
                    self._on_gallery_click(first_item)
            else:
                self._current_file = None
                self._sample_img = None
                self._sample_fg = None
                self.preview_before.clear()
                self.preview_after.clear()
                self.status_label.setText(f"Removed {removed_count} image(s). No images left.")
                self.file_count.setText("0 images found")
                return
        self.file_count.setText(f"{len(self.files)} images found")
        self.status_label.setText(f"Removed {removed_count} image(s)")


    def _set_processing(self, active, n=None):
        # Guard against duplicate/queued finished signals and re-entrancy.
        self._processing = active
        try:
            self.btn_proc.setEnabled(not active)
            self.btn_proc_cur.setEnabled(not active)
        except Exception:
            pass
        if active:
            # Indeterminate (busy) while starting; on_progress sets the real max.
            self.progress.setMaximum(0)
            self.progress.setValue(0)
        else:
            # Reset to a clean, empty (non-busy) state after export.
            self.progress.setMaximum(1)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)

    def _start_worker(self, files, out_dir, canvas_w, canvas_h, margins, anchor, fill, fmt, s_map, fg_map):
        self._set_processing(True, len(files))
        self.worker = ProcessWorker(
            files, out_dir,
            canvas_w, canvas_h, margins, anchor, fill, fmt,
            self.signals, settings_map=s_map, fg_map=fg_map,
        )
        # Signals are connected once in __init__; do not reconnect here
        # to avoid stacked duplicate "Done" popups on repeated runs.
        self.worker.start()

    def process_all(self):
        if not self.files:
            return
        if self._processing:
            return
        self.out_dir = os.path.join(os.path.dirname(self.files[0]), "output")
        os.makedirs(self.out_dir, exist_ok=True)
        # Sync current UI settings (fill, bg_mode, etc.) to ALL images so
        # Process All uses the latest background color regardless of stale
        # per-image settings that may still hold a previous fill value.
        s = self._current_settings()
        s["bg_mode"] = self.bg_mode.currentText()
        for p in self.files:
            self.image_settings[p] = s
        self.status_label.setText(f"Processing {len(self.files)} images...")
        self._start_worker(
            self.files, self.out_dir,
            self.spin_w.value(), self.spin_h.value(), self._margins(),
            self.anchor.currentText(), self._fill(), self.fmt.currentText(),
            self.image_settings, self.image_fg,
        )

    def process_current(self):
        if not self._current_file:
            self.status_label.setText("No current image")
            return
        if self._processing:
            return
        self.out_dir = os.path.join(os.path.dirname(self.files[0]), "output")
        os.makedirs(self.out_dir, exist_ok=True)
        # Sync current UI settings (fill, bg_mode, etc.) to the current file
        # so Process Current uses the latest background color regardless of
        # stale per-image settings.
        s = self._current_settings()
        s["bg_mode"] = self.bg_mode.currentText()
        self.image_settings[self._current_file] = s
        self.status_label.setText(f"Processing {os.path.basename(self._current_file)}...")
        self._start_worker(
            [self._current_file], self.out_dir,
            s.get("w", self.spin_w.value()),
            s.get("h", self.spin_h.value()),
            s.get("margins", self._margins()),
            s.get("anchor", self.anchor.currentText()),
            s.get("fill", self._fill()),
            self.fmt.currentText(), self.image_settings, self.image_fg,
        )

    def on_progress(self, done, total):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
    def on_finished(self):
        if not getattr(self, "_processing", False):
            # Stale signal from a previous run; ignore to avoid duplicate popups.
            return
        self._set_processing(False)
        self.status_label.setText("Done")
        QMessageBox.information(self, "Done", f"Processed into {self.out_dir}")


def main():
    app = QApplication(sys.argv)

    # ---------------------------------------------------------------
    # First-startup: download model + init ONNX session with a
    # user-facing progress dialog.  This replaces the old silent
    # background initialization.  The model is then reused by every
    # subsequent call to remove_background().
    # ---------------------------------------------------------------
    from app.ui.model_load_dialog import ModelLoadDialog

    dialog = ModelLoadDialog()
    worker, thread = ModelLoadDialog.start_worker(dialog)
    thread.started.connect(worker.run)
    thread.start()
    dialog.exec()  # blocks on its own event loop; worker signals update it

    # Clean up thread
    if thread.isRunning():
        thread.quit()
        thread.wait(2000)

    if dialog.result() == 0:  # Rejected → model failed to load
        QMessageBox.critical(
            None,
            "Startup Error",
            "Could not load the background-removal model. "
            "The application will close.",
        )
        sys.exit(1)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()




