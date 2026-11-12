@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

echo ============================================================
echo  1) Put the WeChat mini-program window fully visible first
echo     (white content area complete, no other window on top)
echo  2) Then move the mouse to the TOP-LEFT corner of the
echo     mini-program content area and press Enter
echo  3) Then move the mouse to the BOTTOM-RIGHT corner and
echo     press Enter
echo ============================================================
echo.
%PYEXE% calibrate.py
echo.
echo Check calibration_preview.png : it must contain ONLY the
echo mini-program content area (no title bar, no desktop).
pause
