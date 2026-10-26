p = 'app/ui/main_window.py'
s = open(p).read()
old = '        btn_preview = QPushButton("Remove BG (preview)")\n        btn_preview.clicked.connect(self.remove_bg_preview)\n        ctrl.addWidget(btn_preview)'
new = '        self.bg_mode = QComboBox()\n        self.bg_mode.addItems(["Keep original", "Remove background"])\n        self.bg_mode.currentTextChanged.connect(self._on_bg_mode_changed)\n        ctrl.addWidget(QLabel("Background"))\n        ctrl.addWidget(self.bg_mode)'
if old in s:
    s = s.replace(old, new)
    open(p, 'w').write(s)
    print('step1 done')
else:
    print('old not found')
    lines = s.split('\n')
    for i, l in enumerate(lines[166:172], start=167):
        print(f'{i}: {repr(l)}')

