@echo off
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start_scheduler.ps1"
exit /b
