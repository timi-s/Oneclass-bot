@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion
title OneClass Helper

if not exist "%~dp0gui.py" goto no_gui

rem ---------- 1. locate python interpreter ----------
set "PYEXE="
py -3.13 -V >nul 2>&1
if not errorlevel 1 goto use_py_launcher

python -V >nul 2>&1
if not errorlevel 1 goto use_plain_python
goto no_python

:use_py_launcher
for /f "delims=" %%i in ('py -3.13 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE goto no_python
goto have_python

:use_plain_python
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE goto no_python
goto have_python

:have_python
rem ---------- 2. prefer pythonw.exe next to python.exe (no console window) ----------
set "PYW=!PYEXE:python.exe=pythonw.exe!"
if not exist "!PYW!" set "PYW=!PYEXE!"

if exist "%~dp0gui_crash.log" del /f /q "%~dp0gui_crash.log" >nul 2>&1

rem ---------- 3. start ----------
start "" /D "%~dp0" "!PYW!" "%~dp0gui.py"

rem ---------- 4. wait and check crash log ----------
ping -n 4 127.0.0.1 >nul 2>&1
if not exist "%~dp0gui_crash.log" exit /b 0
echo.
echo [X] GUI failed to start. Details:
echo --------------------------------------------------
type "%~dp0gui_crash.log"
echo --------------------------------------------------
echo Full log: %~dp0gui_crash.log
pause
exit /b 1

:no_gui
echo [X] gui.py not found. Extract the whole zip first, do not run inside the archive.
pause
exit /b 1

:no_python
echo [X] Python not found. Run install.cmd first, or install Python 3.13:
echo     https://www.python.org/downloads/release/python-3139/
pause
exit /b 1
