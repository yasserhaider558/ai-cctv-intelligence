@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI CCTV Intelligence - Setup

echo ============================================================
echo   AI CCTV Intelligence System - Setup
echo ============================================================
echo.

set "PYEXE="

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3.12"

if not defined PYEXE (
    py -3.11 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYEXE=py -3.11"
)

if not defined PYEXE (
    python -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12))" >nul 2>&1
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo [ERROR] A supported Python interpreter was not found.
    echo.
    echo         This project requires Python 3.11 or 3.12, 64-bit.
    echo         Download it from:
    echo             https://www.python.org/downloads/windows/
    echo         During installation tick "Add python.exe to PATH".
    echo.
    echo         Python 3.13 is not supported yet because the PyTorch and
    echo         OpenCV wheels are not reliably available for it.
    echo.
    pause
    exit /b 1
)

echo [1/5] Interpreter:
%PYEXE% --version
echo.

rem The environment lives on D: because the system drive is nearly full and a
rem CUDA build of PyTorch needs several gigabytes. Falls back to a local .venv.
set "VENV_DIR=D:\ai-cctv-env"
if not exist "D:\" set "VENV_DIR=%~dp0.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/5] Creating the virtual environment in %VENV_DIR% ...
    %PYEXE% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo [ERROR] Could not create the virtual environment.
        echo         Check that you have write permission in this folder.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [2/5] Reusing the existing virtual environment.
)

echo.
echo [3/5] Upgrading pip ...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 echo [WARNING] pip could not be upgraded; using the bundled version.

echo.
echo [4/5] Installing dependencies. This takes several minutes on a
echo       first run because PyTorch is a large download.
echo.
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed. Scroll up for the pip message.
    echo         Common causes:
    echo           - no internet access, or a proxy blocking pypi.org
    echo           - a 32-bit Python installation
    echo           - Python 3.13 instead of 3.11/3.12
    echo.
    pause
    exit /b 1
)

echo.
echo [5/5] Verifying that the dependencies import ...
"%VENV_DIR%\Scripts\python.exe" -c "import PySide6, cv2, numpy, ultralytics; print('dependencies OK')"
if errorlevel 1 (
    echo.
    echo [ERROR] The packages installed but fail to import.
    echo         Run this for details:
    echo             "%VENV_DIR%\Scripts\python.exe" -c "import ultralytics"
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup complete.
echo.
echo   Environment:                  %VENV_DIR%
echo   Start the application with:   run.bat
echo   Run the test suite with:      "%VENV_DIR%\Scripts\python.exe" -m pytest
echo.
echo   The first camera connection downloads the YOLO weights
echo   (about 6 MB for yolov8n) into the models folder. Internet
echo   access is needed once; afterwards everything runs offline.
echo ============================================================
echo.
pause
exit /b 0
