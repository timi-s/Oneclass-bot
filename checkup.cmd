@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

echo ==== Checkup: capture the calibrated area, run OCR, guess the page state ====
echo (Nothing will be clicked. It only reads the screen.)
echo.
%PYEXE% checkup.py %*
echo.
echo Screenshot written to checkup.png - open it to see what the bot actually sees.
pause
