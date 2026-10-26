p = 'app/ui/main_window.py'
s = open(p).read()

# Fix apply_to_current: missing update_preview() call and broken string
old1 = '''    def apply_to_current(self):
        try:
            if not self._current_file:
                self.status_label.setText("No current image")
                return
            self.image_settings[self._current_file] = self._current_settings()
            self.status_label.setText(f"Applied settings to {os.path.basename(self._current_file)}\\n            self.update_preview()")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")'''
new1 = '''    def apply_to_current(self):
        try:
            if not self._current_file:
                self.status_label.setText("No current image")
                return
            self.image_settings[self._current_file] = self._current_settings()
            self.update_preview()
            self.status_label.setText(f"Applied settings to {os.path.basename(self._current_file)}")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")'''
assert old1 in s, 'old1 not found'
s = s.replace(old1, new1)
print('fix apply_to_current done')

# Fix apply_to_all: out_dir default, guard at top, update_preview call
old2 = '''    def apply_to_all(self):
        try:
            s = self._current_settings()
            for p in self.files:
                self.image_settings[p] = s
            self.status_label.setText(f"Applied settings to all {len(self.files)} images\\n            self.update_preview()")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")
        if not self.files:
            QMessageBox.warning(self, "No files", "Select a folder first")
            return
        self.progress.setMaximum(len(self.files))
        self.progress.setValue(0)
        self.worker = ProcessWorker(self.files, self.out_dir, self.spin_w.value(),
                                   self.spin_h.value(), self._margins(),
                                   self.anchor.currentText(), self._fill(),
                                   self.fmt.currentText(), self.signals,
                                   settings_map=self.image_settings)
        self.worker.start()'''
new2 = '''    def apply_to_all(self):
        if not self.files:
            QMessageBox.warning(self, "No files", "Select a folder first")
            return
        self.out_dir = self.out_edit.text() or os.path.join(os.path.dirname(self.files[0]), "output")
        os.makedirs(self.out_dir, exist_ok=True)
        try:
            s = self._current_settings()
            for p in self.files:
                self.image_settings[p] = s
            self.update_preview()
            self.status_label.setText(f"Applied settings to all {len(self.files)} images")
        except Exception as e:
            self.status_label.setText(f"apply err: {e}")
        self.progress.setMaximum(len(self.files))
        self.progress.setValue(0)
        self.worker = ProcessWorker(self.files, self.out_dir, self.spin_w.value(),
                                   self.spin_h.value(), self._margins(),
                                   self.anchor.currentText(), self._fill(),
                                   self.fmt.currentText(), self.signals,
                                   settings_map=self.image_settings)
        self.worker.start()'''
assert old2 in s, 'old2 not found'
s = s.replace(old2, new2)
print('fix apply_to_all done')

open(p, 'w').write(s)
print('done')

