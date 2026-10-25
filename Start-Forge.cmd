@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-forge.ps1"
echo.
echo Forge has stopped. Any startup error is shown above.
pause
