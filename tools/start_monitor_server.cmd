@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start_monitor_server.ps1"
exit /b
