@echo off
:: ============================================================
::  Build standalone Windows EXE for Bulk Image Resizer & BG Remover
:: ============================================================
::  Requires: Python with all packages listed in requirements.txt
::            (pyinstaller, PyQt6, rembg, Pillow, onnxruntime)
:: ============================================================
setlocal

cd /d "%~dp0"

echo.
echo [1/3] Verifying Python is on PATH ...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [2/3] Verifying required packages are installed ...
python -c "import PyQt6, rembg, PIL, onnxruntime" 2>nul
if errorlevel 1 (
    echo One or more packages are missing. Installing from requirements.txt ...
    python -m pip install -r requirements.txt
)

echo [3/3] Building single-file EXE with PyInstaller ...
echo.
:: --onefile is implicit (no COLLECT step in spec = one-file mode)
:: --windowed is implicit (console=False in spec = no console popup)
:: --clean: remove build cache before building
python -m PyInstaller --clean --noconfirm bulk_image_resizer.spec

echo.
echo Build complete. The executable is at:
echo   dist\bulk_image_resizer.exe
echo.
echo ============================================================
echo NOTE: On first launch the app will download the u2net model
echo       (~176 MB) from the internet into your user profile.
echo       A progress dialog is shown during download and model init.
echo       Subsequent launches will reuse the cached model.
echo ============================================================
pause
endlocal
