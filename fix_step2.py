p = 'app/ui/main_window.py'
s = open(p).read()

# Change 1: _on_preview_fg - persist fg into image_fg[_current_file]
old1 = '''    def _on_preview_fg(self, fg):
        if fg is None:
            self._model_ready = True
            self.status_label.setText("Model ready")
            return
        self._sample_fg = fg
        self.status_label.setText("Preview ready")
        self.update_preview()'''
new1 = '''    def _on_preview_fg(self, fg):
        if fg is None:
            self._model_ready = True
            self.status_label.setText("Model ready")
            return
        self._sample_fg = fg
        if self._current_file:
            self.image_fg[self._current_file] = fg
        self.status_label.setText("Preview ready")
        self.update_preview()'''
assert old1 in s, 'old1 not found'
s = s.replace(old1, new1)
print('change1 done')

# Change 2: _on_gallery_click - set _current_file first, restore fg, set bg_mode combo
old2 = '''    def _on_gallery_click(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._sample_img = Image.open(p).convert("RGBA")
            self._sample_fg = self.image_fg.get(p)
            self._current_file = p
            s = self.image_settings.get(p)
            if s:
                self.spin_w.setValue(s["w"]); self.spin_h.setValue(s["h"])
                self.sliders["top"].setValue(s["margins"].top); self.sliders["bottom"].setValue(s["margins"].bottom)
                self.sliders["left"].setValue(s["margins"].left); self.sliders["right"].setValue(s["margins"].right)
                self.anchor.setCurrentText(s["anchor"])
            self.update_preview()
            self.status_label.setText(f"Selected: {os.path.basename(p)}")
        except Exception as e:
            self.status_label.setText(f"err: {e}")'''
new2 = '''    def _on_gallery_click(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._current_file = p
            self._sample_img = Image.open(p).convert("RGBA")
            self._sample_fg = self.image_fg.get(p)
            # set bg_mode combo based on whether fg differs from original
            if self._sample_fg is not None:
                self.bg_mode.setCurrentText("Remove background")
            else:
                self.bg_mode.setCurrentText("Keep original")
            s = self.image_settings.get(p)
            if s:
                self.spin_w.setValue(s["w"]); self.spin_h.setValue(s["h"])
                self.sliders["top"].setValue(s["margins"].top); self.sliders["bottom"].setValue(s["margins"].bottom)
                self.sliders["left"].setValue(s["margins"].left); self.sliders["right"].setValue(s["margins"].right)
                self.anchor.setCurrentText(s["anchor"])
            self.update_preview()
            self.status_label.setText(f"Selected: {os.path.basename(p)}")
        except Exception as e:
            self.status_label.setText(f"err: {e}")'''
assert old2 in s, 'old2 not found'
s = s.replace(old2, new2)
print('change2 done')

open(p, 'w').write(s)
print('step2 done')

