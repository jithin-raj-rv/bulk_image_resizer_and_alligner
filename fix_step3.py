p = 'app/ui/main_window.py'
s = open(p).read()

old = '''        self.status_label.setText("Preview ready")
        self.update_preview()

    def _populate_gallery(self):'''
new = '''        self.status_label.setText("Preview ready")
        self.update_preview()

    def _on_bg_mode_changed(self, text):
        if self._sample_img is None or not self._current_file:
            return
        if text == "Remove background":
            self.remove_bg_preview()
        elif text == "Keep original":
            self._sample_fg = self._sample_img.copy()
            self.image_fg[self._current_file] = self._sample_fg
            self.update_preview()
            self.status_label.setText("Background kept")

    def _populate_gallery(self):'''
assert old in s, 'anchor not found'
s = s.replace(old, new)
open(p, 'w').write(s)
print('step3 done')

