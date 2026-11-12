@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Package for sharing

set "PY="
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PY=py -3.13"

if not defined PY (
  python -V >nul 2>&1
  if %errorlevel%==0 set "PY=python"
)

if not defined PY (
  echo.
  echo [X] Python not found. Install Python 3.13 first:
  echo     https://www.python.org/downloads/release/python-3139/
  pause
  exit /b 1
)

%PY% "%~dp0打包.py"
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
