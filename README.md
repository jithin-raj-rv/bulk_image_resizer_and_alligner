

https://github.com/user-attachments/assets/a63f2533-e7cb-4423-991c-03d830dfffd6

# Bulk Image BG Remover + Resizer + Aligner

![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

Python desktop app (PyQt6 GUI + CLI) to remove backgrounds, resize, and align product images with margin bars.

## Features

- Bulk background removal using [rembg](https://github.com/danielgatis/rembg) (u2net model).
- Resize and align images onto a canvas with configurable top/bottom/left/right margins.
- Anchor control and fill color for empty space.
- GUI mode with splash screen and progress dialog.
- CLI mode for batch processing and automation.
- Standalone Windows EXE via PyInstaller (no Python install needed for end users).

## Download (Standalone EXE)

Grab the latest pre-built Windows executable from the [Releases page](https://github.com/jithin-raj-rv/bulk_image_resizer_and_alligner/releases).

> On first launch the app downloads the `u2net` model (~176 MB) into
> `%USERPROFILE%\.u2net` (cached for subsequent runs). A modal progress
> dialog is shown during download and model initialization.

## Run from Source

### Prerequisites
- Python 3.10+
- pip

### Install
```bat
pip install -r requirements.txt
```

### GUI mode
```bat
python main.py
```

### CLI mode
```bat
python main.py <input_folder> -o <out_folder> --w 1000 --h 1000 --top 50 --bottom 50 --left 50 --right 50 --fill 255,255,255
```

First run shows a progress dialog and downloads the u2net model (~176MB)
into `~/.rembg/models`, then initializes the ONNX session. Subsequent runs
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

Output: `dist\bulk_image_resizer\bulk_image_resizer.exe`

### 2. Launch the app
```bat
launch.bat
```
- If `dist\bulk_image_resizer\bulk_image_resizer.exe` exists it runs the standalone EXE.
- Otherwise it falls back to `python main.py` (requires Python + dependencies).

> **NOTE:** On first launch the app downloads the `u2net` model (~176 MB)
> into `~/.rembg/models`. A modal progress dialog is shown during the
> download and model initialization. This is a one-time download per machine;
> subsequent launches reuse the cached model.

### CLI build (optional, for command-line use)
To produce a console-enabled build that shows CLI output, uncomment the
`COLLECT` block and set `console=True` in the `EXE(...)` call inside
`bulk_image_resizer.spec`, then rebuild. Alternatively, run the Python
source directly:
```bat
python main.py <input_folder> -o <out_folder> --w 1000 --h 1000 --top 50 --bottom 50 --left 50 --right 50 --fill 255,255,255
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

## License

This project is licensed under the [MIT License](LICENSE).
