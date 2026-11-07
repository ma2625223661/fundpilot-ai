@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FundPilot AI · 停止网站
echo 正在停止后台运行的 FundPilot AI 网站…
"%~dp0runtime\python.exe" -B "%~dp0backend\launch.py" --stop
timeout /t 3 >nul
