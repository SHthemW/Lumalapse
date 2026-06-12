@echo off
rem ============================================================
rem  Lumalapse launcher
rem    double-click          -> open GUI
rem    Lumalapse.bat <dir> -> open GUI with a sequence/project
rem  First run bootstraps the venv automatically.
rem ============================================================
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYW=%VENV%\Scripts\pythonw.exe"

if exist "%PYW%" goto :launch

echo [Lumalapse] First run: creating virtual environment...
where python >nul 2>nul
if errorlevel 1 (
    echo [Lumalapse] ERROR: Python not found in PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)
python -m venv "%VENV%" || (echo [Lumalapse] ERROR: venv creation failed & pause & exit /b 1)
echo [Lumalapse] Installing dependencies (a few minutes on first run)...
"%VENV%\Scripts\python.exe" -m pip install --quiet -e "%ROOT%." || (
    echo [Lumalapse] ERROR: dependency installation failed
    pause
    exit /b 1
)
echo [Lumalapse] Setup complete.

:launch
start "" "%PYW%" -m lumalapse.cli gui %*
endlocal
