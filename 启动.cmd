@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

if not exist "calibration_preview.png" (
  echo [STOP] Calibration not found. Run calibrate.cmd first.
  echo        Drag the WeChat mini-program window into place, then run calibrate.cmd.
  pause
  exit /b 1
)

echo Starting OneClass word bot ... (Ctrl+C to stop, or slam mouse to top-left corner)
%PYEXE% main.py %*
pause
