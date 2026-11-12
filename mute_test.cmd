@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

echo ==== 静音时还能不能录到声音 ====
echo 建议先取消静音跑一次，再静音跑一次，对比 RMS。
echo.
%PYEXE% mute_test.py %*
echo.
pause
