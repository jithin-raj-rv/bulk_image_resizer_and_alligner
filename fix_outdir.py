p = 'app/ui/main_window.py'
s = open(p).read()

old = '        self.out_dir = self.out_edit.text() or os.path.join(os.path.dirname(self.files[0]), "output")'
new = '        self.out_dir = os.path.join(os.path.dirname(self.files[0]), "output")'

count = s.count(old)
print(f'found {count} occurrences')
s = s.replace(old, new)
open(p, 'w').write(s)
print('done')

