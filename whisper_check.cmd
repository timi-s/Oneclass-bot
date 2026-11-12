@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

echo ==== Whisper 听写自检 ====
echo 1) 先把小程序停在听写题，让声音真的放出来；
echo 2) 再运行本脚本，它会录 3.2 秒回环音频并识别。
echo.
%PYEXE% whisper_check.py %*
echo.
pause
