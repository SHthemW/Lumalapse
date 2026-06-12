@echo off
rem ============================================================
rem  Smoothlapse launcher
rem    double-click          -> open GUI
rem    Smoothlapse.bat <dir> -> open GUI with a sequence/project
rem  First run bootstraps the venv automatically.
rem ============================================================
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYW=%VENV%\Scripts\pythonw.exe"

if exist "%PYW%" goto :launch

echo [Smoothlapse] First run: creating virtual environment...
where python >nul 2>nul
if errorlevel 1 (
    echo [Smoothlapse] ERROR: Python not found in PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)
python -m venv "%VENV%" || (echo [Smoothlapse] ERROR: venv creation failed & pause & exit /b 1)
echo [Smoothlapse] Installing dependencies (a few minutes on first run)...
"%VENV%\Scripts\python.exe" -m pip install --quiet -e "%ROOT%." || (
    echo [Smoothlapse] ERROR: dependency installation failed
    pause
    exit /b 1
)
echo [Smoothlapse] Setup complete.

:launch
start "" "%PYW%" -m smoothlapse.cli gui %*
endlocal
