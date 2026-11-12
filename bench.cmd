@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=python"
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PYEXE=py -3.13"

echo ==== Benchmark: screenshot + OCR (read-only) ====
echo.
%PYEXE% bench.py %*
echo.
pause
