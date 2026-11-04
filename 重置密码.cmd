@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FundPilot AI · 重置密码
if not exist "%~dp0runtime\python.exe" (
    echo 请先完整解压压缩包，再运行本工具。
    pause
    exit /b 1
)
echo 用于找回本机网站的账号密码：输入用户名（或注册邮箱）和新密码。
echo 重置后该账号在所有设备上的登录都会退出。网站可以保持运行。
echo.
"%~dp0runtime\python.exe" -B "%~dp0cloud_admin.py" --local
pause
