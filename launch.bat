@echo off
:: ============================================================
::  Launcher for Bulk Image Resizer & BG Remover
:: ============================================================
::  - If dist\bulk_image_resizer\bulk_image_resizer.exe exists, run the standalone EXE.
::  - Otherwise, fall back to running the Python source directly.
::  - Pass command-line arguments (for CLI mode) after -- or
::    directly; they will be forwarded to the script/EXE.
:: ============================================================
setlocal
cd /d "%~dp0"

set "EXE_PATH=%~dp0dist\bulk_image_resizer\bulk_image_resizer.exe"

if exist "%EXE_PATH%" (
    :: --- Run standalone EXE (GUI mode, no console) ---
    "%EXE_PATH%" %*
    exit /b %errorlevel%
)

:: --- Fallback: run from Python source ---
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found and no EXE was built.
    echo        Install Python 3.10+ or run build_exe.bat first.
    pause
    exit /b 1
)

python "%~dp0main.py" %*
exit /b %errorlevel%

endlocal
