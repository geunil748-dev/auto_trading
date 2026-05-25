@echo off
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start_monitor_server.ps1"
exit /b
