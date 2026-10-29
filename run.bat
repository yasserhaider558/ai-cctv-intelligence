@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI CCTV Intelligence

rem The Python environment lives on D: because the system drive is nearly full
rem and a CUDA build of PyTorch needs several gigabytes. It falls back to a
rem local .venv when D: does not exist.
set "VENV_DIR=D:\ai-cctv-env"
if not exist "D:\" set "VENV_DIR=%~dp0.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ============================================================
    echo   [ERROR] The virtual environment is missing.
    echo.
    echo   Expected at: %VENV_DIR%
    echo   Run setup.bat first. It creates the environment and
    echo   installs the dependencies.
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo Starting AI CCTV Intelligence System ...
echo   environment: %VENV_DIR%
echo.

"%VENV_DIR%\Scripts\python.exe" main.py %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo ============================================================
    echo   [ERROR] The application exited with code %EXITCODE%.
    echo.
    echo   The full log is here: data\logs\app.log
    echo   The console output above usually names the failing module.
    echo ============================================================
    echo.
    pause
)

exit /b %EXITCODE%
