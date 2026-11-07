@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not defined FUNDPILOT_FRONTEND set "FUNDPILOT_FRONTEND=react"
"%~dp0runtime\python.exe" -B "%~dp0backend\launch.py" --check
set "fundpilot_exit=%errorlevel%"
echo.
pause
exit /b %fundpilot_exit%
