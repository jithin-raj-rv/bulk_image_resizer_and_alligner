# Bulk Image BG Remover + Resizer + Aligner

Python desktop app to remove backgrounds, resize, and align product images with margin bars.

## Run

GUI:
```
python main.py
```

CLI:
```
python main.py <input_folder> -o <out_folder> --w 1000 --h 1000 --top 50 --bottom 50 --left 50 --right 50 --fill 255,255,255
```

First run downloads the u2net model (~176MB) into ~/.rembg/models.

## Package
```
pyinstaller --onefile --windowed main.py
```