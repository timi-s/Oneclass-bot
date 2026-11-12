@echo off
chcp 65001 >nul
cd /d "%~dp0"
title OneClass Bot - Setup

rem 找到 Python 3.13（本包依赖按 3.13 编译）
set "PY="
py -3.13 -V >nul 2>&1
if %errorlevel%==0 set "PY=py -3.13"

if not defined PY (
  python -V >nul 2>&1
  if %errorlevel%==0 set "PY=python"
)

if not defined PY (
  echo.
  echo [X] Python not found / Python not installed.
  echo     Trying to install Python 3.13 with winget ...
  echo.
  winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
  py -3.13 -V >nul 2>&1
  if %errorlevel%==0 set "PY=py -3.13"
)

if not defined PY (
  echo.
  echo [X] Still no Python. Please install Python 3.13 manually:
  echo     https://www.python.org/downloads/release/python-3139/
  echo     Tick "Add python.exe to PATH", then run this file again.
  echo.
  start "" "https://www.python.org/downloads/release/python-3139/"
  pause
  exit /b 1
)

rem ---------- 启动界面提示 ----------
if exist "%~dp0启动界面.cmd" (
  echo 提示：装完之后双击 启动界面.cmd 可以用图形界面（推荐）。
  echo.
)

%PY% "%~dp0安装.py"
set "CODE=%errorlevel%"
echo.
if not "%CODE%"=="0" echo [X] Setup failed, exit code %CODE%. Read the messages above.
pause
exit /b %CODE%
