@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 即将以管理员权限启动 VB-CABLE 安装程序。
echo 请在 UAC 弹窗点「是」，然后点 Install Driver，装完重启电脑。
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0vb-cable\VBCABLE_Setup_x64.exe' -Verb RunAs"
echo.
echo 安装器已启动。装完请重启，再回来运行 setup_cable.cmd。
pause
