import os, sys, threading, gc, time, json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QSpinBox, QComboBox, QCheckBox, QFileDialog, QProgressBar,
    QMessageBox, QFrame, QListWidget, QListWidgetItem, QAbstractItemView, QListView, QScrollArea,
    QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PIL import Image, ImageDraw
from app.core.bg_remover import remove_background, has_foreground
from app.core.aligner import Margins, align


def resource_path(relative_path):
    """Get absolute path to a resource, works for dev and for PyInstaller _MEIPASS."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class PreviewSignals(QObject):
    done = pyqtSignal(object)

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    finished = pyqtSignal()
    finished_summary = pyqtSignal(dict)
    error = pyqtSignal(str)
    # Emitted when the worker needs the user to decide.
    # (file_ref, message, kind)  kind in {"lock", "conflict"}
    file_decision_needed = pyqtSignal(str, str, str)


class ProcessWorker(threading.Thread):
    def __init__(self, files, out_dir, canvas_w, canvas_h, margins, anchor, fill, fmt, signals, settings_map=None, fg_map=None, overwrite_existing=True, conflict_policy="overwrite", apply_to_all_conflict=True, max_retries=3, retry_delay=1.5):
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
        if conflict_policy == "overwrite" and not overwrite_existing:
            conflict_policy = "skip"
        self.conflict_policy = conflict_policy
        self.apply_to_all_conflict = apply_to_all_conflict
        self.max_retries = max(1, int(max_retries))
        self.retry_delay = float(retry_delay)
        # Per-file user-decision protocol (worker blocks until GUI replies).
        self.decision = None
        self.decision_apply_all = False
        self.decision_event = threading.Event()
        # Stored "apply to all" decisions (once the user ticks the box).
        self._stored_lock_decision = None
        self._stored_conflict_decision = None

    def run(self):
        os.makedirs(self.out_dir, exist_ok=True)
        total = len(self.files)
        stats = {
            "ok": 0, "overwritten": 0, "renamed": 0,
            "skipped_no_fg": 0, "skipped_exists": 0, "skipped_locked": 0, "failed": 0,
        }
        failed_files = []
        for i, f in enumerate(self.files):
            if self.cancel:
                self.signals.status.emit("Cancelled")
                break
            self.signals.status.emit(f"Processing {os.path.basename(f)}")
            img = None
            try:
                s_per = self.settings_map.get(f, {})
                bg_mode = s_per.get("bg_mode", "Remove background")
                # Use cached foreground (edited preview) when available so
                # re-processing after edits exports the edited image.
                fg = self.fg_map.get(f)
                if fg is not None:
                    fg = fg.copy()
                else:
                    # --- open source image (may be locked by another app) ---
                    img = self._open_with_retry(f)
                    if img is None:
                        # User chose skip/abort for a locked source file.
                        if self.cancel:
                            self.signals.status.emit("Aborted by user")
                            break
                        stats["skipped_locked"] += 1
                        failed_files.append((f, "source file is open in another app"))
                        self.signals.status.emit(f"skip (locked): {os.path.basename(f)}")
                        continue
                    if bg_mode == "Keep original":
                        fg = img.copy()
                    else:
                        fg = remove_background(img)
                if not has_foreground(fg):
                    self.signals.status.emit(f"skip (no foreground): {os.path.basename(f)}")
                    stats["skipped_no_fg"] += 1
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

                    # --- resolve existing-file conflict ---
                    final_path, action, skip = self._resolve_out_path(f, out_path)
                    if skip:
                        stats["skipped_exists"] += 1
                        self.signals.status.emit(f"skip (exists): {os.path.basename(out_path)}")
                        continue

                    # --- save destination (may be locked by another app) ---
                    saved = self._save_with_retry(canvas, final_path, f)
                    if not saved:
                        if self.cancel:
                            self.signals.status.emit("Aborted by user")
                            break
                        stats["skipped_locked"] += 1
                        failed_files.append((final_path, "output file is open in another app"))
                        self.signals.status.emit(f"skip (locked): {os.path.basename(final_path)}")
                        continue

                    if action == "overwritten":
                        stats["overwritten"] += 1
                        self.signals.status.emit(f"overwritten: {os.path.basename(final_path)}")
                    elif action == "renamed":
                        stats["renamed"] += 1
                        self.signals.status.emit(f"renamed: {os.path.basename(final_path)}")
                    else:
                        stats["ok"] += 1
                        self.signals.status.emit(f"saved: {os.path.basename(final_path)}")
            except Exception as e:
                stats["failed"] += 1
                failed_files.append((f, str(e)))
                self.signals.error.emit(f"{f}: {e}")
            finally:
                try:
                    if img is not None:
                        img.close()
                except Exception:
                    pass
            self.signals.progress.emit(i + 1, total)

        self.signals.finished.emit()
        self.signals.finished_summary.emit({
            "stats": stats,
            "failed_files": failed_files,
            "out_dir": self.out_dir,
        })

    # ------------------------------------------------------------------
    # Retry helpers for files locked by another app
    # ------------------------------------------------------------------
    def _open_with_retry(self, path):
        """Open an image, retrying on locked-file errors. Prompts the user
        when retries are exhausted. Returns None on skip/abort/cancel."""
        while True:
            last_err = None
            for attempt in range(1, self.max_retries + 1):
                if self.cancel:
                    return None
                try:
                    return Image.open(path).convert("RGBA")
                except (OSError, PermissionError) as e:
                    last_err = e
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
            decision = self._prompt(path,
                                    f"Source image is open in another app:\n{os.path.basename(path)}\n({last_err})",
                                    "lock")
            if decision == "retry":
                continue
            if decision == "skip":
                return None
            # abort
            self.cancel = True
            return None

    def _save_with_retry(self, canvas, out_path, source_label):
        """Save the canvas, retrying on locked-file errors. Prompts the user
        when retries are exhausted. Returns False on skip/abort/cancel."""
        while True:
            last_err = None
            for attempt in range(1, self.max_retries + 1):
                if self.cancel:
                    return False
                try:
                    canvas.save(out_path)
                    return True
                except (OSError, PermissionError) as e:
                    last_err = e
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
            decision = self._prompt(source_label,
                                    f"Output file is open in another app:\n{os.path.basename(out_path)}\n({last_err})",
                                    "lock")
            if decision == "retry":
                continue
            if decision == "skip":
                return False
            self.cancel = True
            return False

    def _resolve_out_path(self, f, out_path):
        """Resolve an existing output file according to conflict policy.
        Returns (final_path, action, skip) where skip=True means skip this file."""
        if not os.path.exists(out_path):
            return out_path, "ok", False
        policy = self.conflict_policy
        if policy == "overwrite" and not self.overwrite_existing:
            policy = "skip"
        if policy == "skip":
            return out_path, "ok", True
        if policy == "overwrite":
            return out_path, "overwritten", False
        if policy == "rename":
            stem, ext = os.path.splitext(out_path)
            counter = 2
            candidate = f"{stem}_{counter}{ext}"
            while os.path.exists(candidate):
                counter += 1
                candidate = f"{stem}_{counter}{ext}"
            return candidate, "renamed", False
        # "ask" -> prompt the user (with optional apply-to-all)
        decision = self._prompt(f,
                                f"Output file already exists:\n{os.path.basename(out_path)}\nChoose how to handle it.",
                                "conflict")
        if decision == "overwrite":
            return out_path, "overwritten", False
        if decision == "rename":
            stem, ext = os.path.splitext(out_path)
            counter = 2
            candidate = f"{stem}_{counter}{ext}"
            while os.path.exists(candidate):
                counter += 1
                candidate = f"{stem}_{counter}{ext}"
            return candidate, "renamed", False
        # skip / cancel / abort
        return out_path, "ok", True

    def _prompt(self, file_ref, message, kind):
        """Show a decision dialog on the GUI thread and block until it answers.
        Honors any stored "apply to all" decision. Returns the chosen decision."""
        stored = self._stored_lock_decision if kind == "lock" else self._stored_conflict_decision
        if stored is not None:
            return stored
        self.decision = None
        self.decision_apply_all = False
        self.decision_event.clear()
        self.signals.file_decision_needed.emit(file_ref, message, kind)
        self.decision_event.wait()
        decision = self.decision or "skip"
        if self.decision_apply_all:
            if kind == "lock":
                self._stored_lock_decision = decision
            else:
                self._stored_conflict_decision = decision
        return decision


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
        self.setWindowIcon(QIcon(resource_path("logo.png")))
        self.resize(1000, 700)
        self.setMinimumSize(900, 650)
        self.files = []
        self.image_settings = {}
        self.image_fg = {}
        self._current_file = None
        self.out_dir = None
        self.worker = None
        self._processing = False
        # Custom background colors (display name -> RGBA tuple)
        # Must be initialized before _build() because _refresh_fill_combo() reads it.
        self.custom_colors = {}
        self._custom_colors_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "custom_colors.json"
        )
        self._build()
        self.setAcceptDrops(True)
        self.prev_signals = PreviewSignals()
        self.prev_signals.done.connect(self._on_preview_fg)
        self._model_ready = True  # model preloaded in main() before MainWindow
        # Default processing settings (persisted to JSON)
        self.default_settings = {}
        self._defaults_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "default_settings.json"
        )
        self._load_custom_colors()
        self._load_default_settings()
        self._apply_defaults_to_ui()
        self.signals = WorkerSignals()
        self.signals.progress.connect(self.on_progress)
        self.signals.status.connect(self.status_label.setText)
        self.signals.finished.connect(self.on_finished)
        self.signals.finished_summary.connect(self.on_finished_summary)
        self.signals.error.connect(lambda e: self.status_label.setText(f"ERR: {e}"))
        self.signals.file_decision_needed.connect(self.on_file_decision_needed)

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
        self.btn_credits = QPushButton("Credits")
        self.btn_credits.clicked.connect(self.show_credits)
        ctrl.addWidget(self.btn_credits)

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
        self._refresh_fill_combo()
        self.fill_combo.currentTextChanged.connect(self.update_preview)
        ctrl.addWidget(QLabel("Background fill"))
        ctrl.addWidget(self.fill_combo)

        # --- Custom color management ---
        custom_row = QHBoxLayout()
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("Color name (e.g. My Brand)")
        self.custom_name.setFixedWidth(160)
        custom_row.addWidget(self.custom_name)
        self.custom_hex = QLineEdit()
        self.custom_hex.setPlaceholderText("Hex code (e.g. #EEEFF1)")
        self.custom_hex.setFixedWidth(130)
        custom_row.addWidget(self.custom_hex)
        btn_add_color = QPushButton("Add Color")
        btn_add_color.setFixedWidth(90)
        btn_add_color.clicked.connect(self._add_custom_color)
        custom_row.addWidget(btn_add_color)
        ctrl.addLayout(custom_row)

        btn_del_color = QPushButton("Delete Selected Color")
        btn_del_color.clicked.connect(self._delete_custom_color)
        ctrl.addWidget(btn_del_color)

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
        btn_set_default = QPushButton("Set as Default")
        btn_set_default.setToolTip("Save current settings as defaults for all newly added images")
        btn_set_default.clicked.connect(self._set_defaults)
        ctrl.addWidget(btn_set_default)

        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self.remove_selected)
        ctrl.addWidget(btn_remove)

        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems([
            "Overwrite existing",
            "Skip existing",
            "Rename with number",
            "Ask per file",
        ])
        self.conflict_combo.setCurrentText("Overwrite existing")
        ctrl.addWidget(QLabel("If output file already exists:"))
        ctrl.addWidget(self.conflict_combo)

        self.apply_all_conflict = QCheckBox("Apply choice to all files")
        self.apply_all_conflict.setChecked(True)
        ctrl.addWidget(self.apply_all_conflict)

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
            # Auto-apply default settings to all newly loaded images
            self._apply_defaults_to_new_files(self.files)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.status_label.setText(f"err: {e}")

    def _margins(self):
        return Margins(top=self.sliders["top"].value(),
                      bottom=self.sliders["bottom"].value(),
                      left=self.sliders["left"].value(),
                      right=self.sliders["right"].value())

    # ------------------------------------------------------------------
    # Custom color management
    # ------------------------------------------------------------------
    BUILTIN_FILLS = {"transparent", "white", "black", "Light Grey"}

    def _builtin_rgba(self, name: str):
        if name == "transparent":
            return (0, 0, 0, 0)
        if name == "white":
            return (255, 255, 255, 255)
        if name == "Light Grey":
            return (238, 239, 241, 255)
        if name == "black":
            return (0, 0, 0, 255)
        return None

    def _validate_hex(self, hex_str: str):
        """Return (r, g, b, a) tuple if *hex_str* is a valid #RRGGBB color, else None."""
        s = hex_str.strip()
        if not s.startswith("#") or len(s) != 7:
            return None
        try:
            r = int(s[1:3], 16)
            g = int(s[3:5], 16)
            b = int(s[5:7], 16)
        except ValueError:
            return None
        return (r, g, b, 255)

    def _refresh_fill_combo(self):
        """Rebuild the fill combo from built-ins + custom colors."""
        current = self.fill_combo.currentText()
        self.fill_combo.clear()
        self.fill_combo.addItems(["transparent", "white", "black", "Light Grey"])
        for name in self.custom_colors:
            self.fill_combo.addItem(name)
        # Restore previous selection if it still exists
        index = self.fill_combo.findText(current)
        if index >= 0:
            self.fill_combo.setCurrentIndex(index)

    def _load_custom_colors(self):
        """Load custom colors from the JSON persistence file."""
        try:
            if os.path.isfile(self._custom_colors_path):
                with open(self._custom_colors_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for name, rgba in data.items():
                        if isinstance(rgba, list) and len(rgba) == 4:
                            self.custom_colors[name] = tuple(rgba)
        except (json.JSONDecodeError, OSError) as e:
            self.status_label.setText(f"Warning: could not load custom colors: {e}")

    def _save_custom_colors(self):
        """Persist custom colors to the JSON file."""
        try:
            data = {name: list(rgba) for name, rgba in self.custom_colors.items()}
            with open(self._custom_colors_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not save custom colors: {e}")

    def _add_custom_color(self):
        """Add a user-defined color from the name/hex inputs."""
        name = self.custom_name.text().strip()
        hex_str = self.custom_hex.text().strip()

        if not name:
            QMessageBox.warning(self, "Invalid input", "Please enter a color name.")
            return
        if not hex_str:
            QMessageBox.warning(self, "Invalid input", "Please enter a hex color code.")
            return

        rgba = self._validate_hex(hex_str)
        if rgba is None:
            QMessageBox.warning(
                self,
                "Invalid color",
                f"'{hex_str}' is not a valid hex color. Use format #RRGGBB (e.g. #EEEFF1).",
            )
            return

        if name in self.BUILTIN_FILLS or name in self.custom_colors:
            QMessageBox.warning(
                self, "Duplicate name", f"A color named '{name}' already exists."
            )
            return

        self.custom_colors[name] = rgba
        self._save_custom_colors()
        self._refresh_fill_combo()
        self.fill_combo.setCurrentText(name)
        self.custom_name.clear()
        self.custom_hex.clear()
        self.update_preview()
        self.status_label.setText(f"Added custom color '{name}' ({hex_str})")

    def _delete_custom_color(self):
        """Delete the currently selected custom color from the combo."""
        name = self.fill_combo.currentText()
        if name in self.BUILTIN_FILLS:
            QMessageBox.warning(
                self, "Cannot delete", f"'{name}' is a built-in color and cannot be deleted."
            )
            return
        if name not in self.custom_colors:
            QMessageBox.warning(self, "Not a custom color", "Select a custom color to delete.")
            return

        del self.custom_colors[name]
        self._save_custom_colors()
        self._refresh_fill_combo()
        self.update_preview()
        self.status_label.setText(f"Deleted custom color '{name}'")

    def _fill(self):
        v = self.fill_combo.currentText()
        if v in self.custom_colors:
            return self.custom_colors[v]
        rgba = self._builtin_rgba(v)
        if rgba is not None:
            return rgba
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
        # bg mode is only persisted when the user clicks Apply to selected /
        # Apply to all. Here we only update the preview for the current image.
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
                # restore saved fill onto the combo (triggers preview only, not a settings write)
                saved_fill = s.get("fill")
                if saved_fill is not None:
                    # Try built-in colors first
                    name = None
                    if saved_fill == (0, 0, 0, 0):
                        name = "transparent"
                    elif saved_fill == (255, 255, 255, 255):
                        name = "white"
                    elif saved_fill == (238, 239, 241, 255):
                        name = "Light Grey"
                    elif saved_fill == (0, 0, 0, 255):
                        name = "black"
                    # Then try custom colors
                    if name is None:
                        for cname, crgba in self.custom_colors.items():
                            if crgba == saved_fill:
                                name = cname
                                break
                    if name is not None:
                        self.fill_combo.setCurrentText(name)
                    else:
                        self.fill_combo.setCurrentText("black")
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
                new_paths = [p for p in paths if p not in existing]
                for p in new_paths:
                    self.files.append(p)
                self.files = sorted(self.files)
                self._sample_img = Image.open(self.files[0]).convert("RGBA")
                self._sample_fg = None
                self._current_file = self.files[0] if self.files else None
                self._populate_gallery()
                self.status_label.setText(f"Loaded {len(self.files)} images (drag & drop)")
                self.update_preview()
                # Auto-apply default settings to newly added images
                if new_paths:
                    self._apply_defaults_to_new_files(new_paths)
            event.acceptProposedAction()
        except Exception as e:
            self.status_label.setText(f"drop err: {e}")
            event.ignore()

    def _current_settings(self):
        m = Margins(top=self.sliders["top"].value(), bottom=self.sliders["bottom"].value(),
                    left=self.sliders["left"].value(), right=self.sliders["right"].value())
        return {"w": self.spin_w.value(), "h": self.spin_h.value(),
                "margins": m, "anchor": self.anchor.currentText(),
                "fill": self._fill(), "bg_mode": self.bg_mode.currentText()}

    # ------------------------------------------------------------------
    # Default settings persistence
    # ------------------------------------------------------------------
    def _save_default_settings(self):
        """Persist default settings to JSON file."""
        try:
            data = {
                "w": self.default_settings.get("w", self.spin_w.value()),
                "h": self.default_settings.get("h", self.spin_h.value()),
                "margins": {
                    "top": self.default_settings.get("margins", Margins()).top,
                    "bottom": self.default_settings.get("margins", Margins()).bottom,
                    "left": self.default_settings.get("margins", Margins()).left,
                    "right": self.default_settings.get("margins", Margins()).right,
                },
                "anchor": self.default_settings.get("anchor", self.anchor.currentText()),
                "fill": list(self.default_settings.get("fill", self._fill())),
                "bg_mode": self.default_settings.get("bg_mode", self.bg_mode.currentText()),
            }
            with open(self._defaults_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not save default settings: {e}")
            raise

    def _load_default_settings(self):
        """Load default settings from JSON file."""
        try:
            if os.path.isfile(self._defaults_path):
                with open(self._defaults_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    m = Margins(
                        top=data.get("margins", {}).get("top", 0),
                        bottom=data.get("margins", {}).get("bottom", 0),
                        left=data.get("margins", {}).get("left", 0),
                        right=data.get("margins", {}).get("right", 0),
                    )
                    fill = data.get("fill", [0, 0, 0, 255])
                    self.default_settings = {
                        "w": data.get("w", 0),
                        "h": data.get("h", 0),
                        "margins": m,
                        "anchor": data.get("anchor", "center"),
                        "fill": tuple(fill) if isinstance(fill, list) and len(fill) == 4 else (0, 0, 0, 255),
                        "bg_mode": data.get("bg_mode", "Remove background"),
                    }
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
            self.status_label.setText(f"Warning: could not load default settings: {e}")
            self.default_settings = {}

    def _set_defaults(self):
        """Save current UI settings as the default for all new images."""
        try:
            s = self._current_settings()
            self.default_settings = dict(s)
            self._save_default_settings()
            # Apply defaults to all currently loaded images too
            if self.files:
                for p in self.files:
                    if p not in self.image_settings:
                        self.image_settings[p] = dict(s)
            self.status_label.setText("Default settings saved. New images will use these automatically.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not set defaults: {e}")

    def _apply_defaults_to_new_files(self, paths):
        """Apply saved default settings to a list of newly added file paths."""
        if not self.default_settings:
            return
        s = dict(self.default_settings)
        applied = 0
        for p in paths:
            if p not in self.image_settings:
                self.image_settings[p] = s
                applied += 1
        if applied:
            self.status_label.setText(
                f"Default settings applied to {applied} new image(s)."
            )

    def _apply_defaults_to_ui(self):
        """Push saved default settings onto the UI controls at startup."""
        if not self.default_settings:
            return
        try:
            # Block signals so setting values does not trigger update_preview()
            # before an image is loaded.
            widgets = [
                self.spin_w, self.spin_h, self.anchor, self.bg_mode, self.fill_combo,
            ] + list(self.sliders.values())
            for w in widgets:
                w.blockSignals(True)

            s = self.default_settings
            self.spin_w.setValue(int(s.get("w", self.spin_w.value())))
            self.spin_h.setValue(int(s.get("h", self.spin_h.value())))

            m = s.get("margins")
            if isinstance(m, Margins):
                self.sliders["top"].setValue(m.top)
                self.sliders["bottom"].setValue(m.bottom)
                self.sliders["left"].setValue(m.left)
                self.sliders["right"].setValue(m.right)
            elif isinstance(m, dict):
                self.sliders["top"].setValue(int(m.get("top", 0)))
                self.sliders["bottom"].setValue(int(m.get("bottom", 0)))
                self.sliders["left"].setValue(int(m.get("left", 0)))
                self.sliders["right"].setValue(int(m.get("right", 0)))

            anchor = s.get("anchor")
            if anchor:
                self.anchor.setCurrentText(anchor)

            bg_mode = s.get("bg_mode")
            if bg_mode:
                self.bg_mode.setCurrentText(bg_mode)

            # Map saved fill RGBA back to a combo display name.
            fill = s.get("fill")
            if fill is not None:
                name = None
                if fill == (0, 0, 0, 0):
                    name = "transparent"
                elif fill == (255, 255, 255, 255):
                    name = "white"
                elif fill == (238, 239, 241, 255):
                    name = "Light Grey"
                elif fill == (0, 0, 0, 255):
                    name = "black"
                else:
                    for cname, crgba in self.custom_colors.items():
                        if crgba == fill:
                            name = cname
                            break
                if name is not None:
                    self.fill_combo.setCurrentText(name)
        except Exception as e:
            self.status_label.setText(f"Warning: could not apply defaults to UI: {e}")
        finally:
            for w in widgets:
                try:
                    w.blockSignals(False)
                except Exception:
                    pass

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
        policy_map = {
            "Overwrite existing": "overwrite",
            "Skip existing": "skip",
            "Rename with number": "rename",
            "Ask per file": "ask",
        }
        policy = policy_map.get(self.conflict_combo.currentText(), "overwrite")
        self.worker = ProcessWorker(
            files, out_dir,
            canvas_w, canvas_h, margins, anchor, fill, fmt,
            self.signals, settings_map=s_map, fg_map=fg_map,
            conflict_policy=policy,
            apply_to_all_conflict=self.apply_all_conflict.isChecked(),
            max_retries=3,
            retry_delay=1.5,
        )
        # Signals are connected once in __init__; do not reconnect here
        # to avoid stacked duplicate "Done" popups on repeated runs.
        self.worker.start()

    def process_all(self):
        if not self.files:
            return
        if self._processing:
            return
        # Only export images that have saved per-image settings. Live global
        # control values are never auto-applied to images without saved settings.
        files_to_process = [f for f in self.files if f in self.image_settings]
        if not files_to_process:
            self.status_label.setText("No saved settings – apply settings to images first, then Process All.")
            return
        self.out_dir = os.path.join(os.path.dirname(self.files[0]), "output")
        os.makedirs(self.out_dir, exist_ok=True)
        self.status_label.setText(f"Processing {len(files_to_process)} images...")
        self._start_worker(
            files_to_process, self.out_dir,
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
        s = self.image_settings.get(self._current_file, {})
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

    def on_finished_summary(self, summary):
        stats = summary.get("stats", {})
        failed_files = summary.get("failed_files", [])
        out_dir = summary.get("out_dir", "")
        lines = [
            f"Processed : {stats.get('ok', 0)}",
            f"Overwritten: {stats.get('overwritten', 0)}",
            f"Renamed   : {stats.get('renamed', 0)}",
            f"Skipped (no foreground): {stats.get('skipped_no_fg', 0)}",
            f"Skipped (already exists): {stats.get('skipped_exists', 0)}",
            f"Skipped (file in use): {stats.get('skipped_locked', 0)}",
            f"Failed    : {stats.get('failed', 0)}",
        ]
        if failed_files:
            lines.append("")
            lines.append("Failed files:")
            for path, err in failed_files[:20]:
                lines.append(f"  - {os.path.basename(path)}: {err}")
            if len(failed_files) > 20:
                lines.append(f"  ... and {len(failed_files) - 20} more")
        msg = "\n".join(lines)
        QMessageBox.information(self, "Process All – Summary",
                                msg + f"\n\nOutput folder:\n{out_dir}")

    def show_credits(self):
        text = (
            'Instagram: <a href="https://www.instagram.com/jithin_raj_rv/">jithin_raj_rv</a><br>'
            'LinkedIn: <a href="https://www.linkedin.com/in/jithin-raj-rv/">jithin-raj-rv</a><br>'
            'Website: <a href="https://www.jithinrajrv.com/">www.jithinrajrv.com</a><br>'
            'GitHub: <a href="https://github.com/jithin-raj-rv/">jithin-raj-rv</a><br><br>'
            'Made with lots of \U0001FAB2 by Jithin<br><br>'
            'P.S. Gift me a lambar gambar'
        )
        box = QMessageBox(self)
        box.setWindowTitle("Credits")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.exec()

    def on_file_decision_needed(self, file_ref, message, kind):
        """User-facing dialog for locked files / existing-file conflicts.
        Runs on the GUI thread; unblocks the worker once a choice is made."""
        if kind == "lock":
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("File is in use")
            box.setText(message)
            btn_retry = box.addButton("Retry", QMessageBox.ButtonRole.ActionRole)
            btn_skip = box.addButton("Skip", QMessageBox.ButtonRole.ActionRole)
            btn_abort = box.addButton("Abort", QMessageBox.ButtonRole.RejectRole)
        else:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Output file already exists")
            box.setText(message)
            btn_over = box.addButton("Overwrite", QMessageBox.ButtonRole.ActionRole)
            btn_skip = box.addButton("Skip", QMessageBox.ButtonRole.ActionRole)
            btn_rename = box.addButton("Rename", QMessageBox.ButtonRole.ActionRole)
            btn_abort = box.addButton("Cancel all", QMessageBox.ButtonRole.RejectRole)

        cb = QCheckBox("Apply to all remaining files")
        cb.setChecked(self.apply_all_conflict.isChecked())
        box.setCheckBox(cb)
        if kind == "lock":
            box.setDefaultButton(btn_retry)
            box.setEscapeButton(btn_skip)
            mapping = {btn_retry: "retry", btn_skip: "skip", btn_abort: "abort"}
        else:
            box.setDefaultButton(btn_over)
            box.setEscapeButton(btn_skip)
            mapping = {btn_over: "overwrite", btn_skip: "skip",
                       btn_rename: "rename", btn_abort: "abort"}

        box.exec()

        worker = self.worker
        if worker is not None:
            clicked = box.clickedButton()
            worker.decision = mapping.get(clicked, "skip")
            worker.decision_apply_all = cb.isChecked()
            worker.decision_event.set()


def create_main_window(app: QApplication | None = None, splash=None):
    """Create and show the main window.  Called after the splash is visible.

    Does NOT call app.exec() or sys.exit() — the caller owns the event loop.
    """
    if app is None:
        app = QApplication(sys.argv)

    # ---------------------------------------------------------------
    # First-startup: download model + init ONNX session with a
    # user-facing progress dialog.  This replaces the old silent
    # background initialization.  The model is then reused by every
    # subsequent call to remove_background().
    #
    # Retries on a network failure so the user can reconnect and try
    # again instead of the app exiting immediately.
    # ---------------------------------------------------------------
    from app.ui.model_load_dialog import ModelLoadDialog

    while True:
        dialog = ModelLoadDialog()
        worker, thread = ModelLoadDialog.start_worker(dialog)
        thread.started.connect(worker.run)
        thread.start()
        dialog.exec()  # blocks on its own event loop; worker signals update it

        # Clean up thread
        if thread.isRunning():
            thread.quit()
            thread.wait(2000)

        if dialog.result() != 0:  # Accepted → model ready
            break

        # Rejected → model failed to load.
        if getattr(dialog, "_network_error", False):
            # Ask whether to retry (user may have reconnected) or exit.
            reply = QMessageBox.critical(
                None,
                "No Internet Connection",
                (
                    "The background-removal model (~176 MB) could not be "
                    "downloaded because there is no internet connection.\n\n"
                    "Please check your network and click Retry, or click "
                    "Abort to close the application.\n\n"
                    f"Details: {getattr(dialog, '_last_error', '')}"
                ),
                QMessageBox.StandardButton.Retry
                | QMessageBox.StandardButton.Abort,
                QMessageBox.StandardButton.Retry,
            )
            if reply == QMessageBox.StandardButton.Retry:
                continue  # retry the download
            sys.exit(1)

        QMessageBox.critical(
            None,
            "Startup Error",
            "Could not load the background-removal model. "
            "The application will close.",
        )
        sys.exit(1)

    # Dismiss the early startup splash before showing the main window.
    if splash is not None:
        splash.close()
        app.processEvents()

    w = MainWindow()
    w.show()


def main(app: QApplication | None = None, splash=None):
    if app is None:
        app = QApplication(sys.argv)
    create_main_window(app=app, splash=splash)
    sys.exit(app.exec())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()




