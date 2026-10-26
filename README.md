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

First run shows a progress dialog and downloads the u2net model (~176MB)
into ~/.rembg/models, then initializes the ONNX session.  Subsequent runs
reuse the cached model.

## Package (Standalone EXE)

A PyInstaller spec file (`bulk_image_resizer.spec`) is included that correctly
handles the `app` package, rembg's dynamic imports, and PyQt6.

### 1. Build the EXE
```bat
build_exe.bat
```
Or manually:
```bat
python -m PyInstaller --clean --noconfirm bulk_image_resizer.spec
```

Output: `dist\bulk_image_resizer.exe`

### 2. Launch the app
```bat
launch.bat
```
- If `dist\bulk_image_resizer.exe` exists it runs the standalone EXE.
- Otherwise it falls back to `python main.py` (requires Python + dependencies).

> **NOTE:** On first launch the app downloads the `u2net` model (~176 MB)
> into `~/.rembg/models`.  A modal progress dialog is shown during the
> download and model initialization.  This is a one-time download per machine;
> subsequent launches reuse the cached model.

### CLI build (optional, for command-line use)
To produce a console-enabled build that shows CLI output, uncomment the
`COLLECT` block and set `console=True` in the `EXE(...)` call inside
`bulk_image_resizer.spec`, then rebuild.  Alternatively, run the Python
source directly:

```bat
python main.py <input_folder> -o <out_folder> --w 1000 --h 1000 --top 50 --bottom 50 --left 50 --right 50 --fill 255,255,255
```
