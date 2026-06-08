@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
powershell.exe -ExecutionPolicy Bypass -File "%~dp0stop_monitor_server.ps1" %*
exit /b %ERRORLEVEL%
