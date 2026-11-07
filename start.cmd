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
rem 默认使用新版 React 界面；临时改回旧版可先 set FUNDPILOT_FRONTEND=legacy 再运行。
if not defined FUNDPILOT_FRONTEND set "FUNDPILOT_FRONTEND=react"
rem 默认在后台运行（不显示窗口）；加 --console 可带窗口运行，便于排查问题。
"%~dp0runtime\python.exe" -B "%~dp0launch.py" --reload --background %*
set "fundpilot_exit=%errorlevel%"
if not "%fundpilot_exit%"=="0" pause
exit /b %fundpilot_exit%
