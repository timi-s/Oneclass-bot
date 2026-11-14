@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion
title OneClass Helper

if not exist "%~dp0gui.py" goto no_gui

set "PYEXE="
py -3.13 -V >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%i in ('py -3.13 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
)
if not defined PYEXE (
  python -V >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
  )
)
if not defined PYEXE goto no_python

set "PYTHONPATH=%~dp0site-packages"
"%PYEXE%" -c "import yaml, cv2, mss, pyautogui" >nul 2>&1
if errorlevel 1 goto deps_missing

set "PYW=!PYEXE:python.exe=pythonw.exe!"
if not exist "!PYW!" set "PYW=!PYEXE!"

if exist "%~dp0gui_crash.log" del /f /q "%~dp0gui_crash.log" >nul 2>&1
start "" /D "%~dp0" "!PYW!" "%~dp0gui.py"
ping -n 4 127.0.0.1 >nul 2>&1
if not exist "%~dp0gui_crash.log" exit /b 0
echo.
echo [X] GUI failed to start. Details:
echo --------------------------------------------------
type "%~dp0gui_crash.log"
echo --------------------------------------------------
pause
exit /b 1

:no_gui
echo [X] gui.py not found. Extract the whole zip first.
pause
exit /b 1

:no_python
echo [X] Python not found. Run install.cmd first, or install Python 3.13:
echo     https://www.python.org/downloads/release/python-3139/
pause
exit /b 1

:deps_missing
echo.
echo [X] Python found, but dependencies are missing or Python version is wrong.
echo     Run install.cmd to install them.
echo.
echo     Python: %PYEXE%
"%PYEXE%" -V
echo     Tried: import yaml, cv2, mss, pyautogui
echo.
pause
exit /b 1
