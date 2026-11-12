@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Calibrate: mark-as-too-easy

set "PY="
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PY=py -3.13"
if not defined PY (
  python -V >nul 2>&1
  if %errorlevel%==0 set "PY=python"
)
if not defined PY (
  echo [X] Python not found. Run install.cmd first.
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0site-packages"
set "PYTHONIOENCODING=utf-8"
%PY% "%~dp0calibrate_too_easy.py"
echo.
pause
