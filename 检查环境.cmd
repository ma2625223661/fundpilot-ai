@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
"%~dp0runtime\python.exe" -B "%~dp0launch.py" --check
set "fundpilot_exit=%errorlevel%"
echo.
pause
exit /b %fundpilot_exit%
