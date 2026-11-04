@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FundPilot AI
if not exist "%~dp0runtime\python.exe" (
    echo 请先完整解压压缩包，再运行 start.cmd。
    pause
    exit /b 1
)
"%~dp0runtime\python.exe" -B "%~dp0launch.py" %*
set "fundpilot_exit=%errorlevel%"
if not "%fundpilot_exit%"=="0" pause
exit /b %fundpilot_exit%
