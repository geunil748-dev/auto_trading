auto_trading Windows setup guide
================================

This folder contains scripts for setting up auto_trading on a new Windows PC
or AWS Windows server.

Files
-----
setup_windows.ps1
  First-run setup script. It can create .env, create .venv, install packages,
  initialize the database, register scheduled tasks, and start services.

register_windows_tasks.ps1
  Registers two Windows scheduled tasks:
  - AutoTrading-Monitor
  - AutoTrading-Scheduler

Before running
--------------
1. Install Git.
2. Install Python 3.11 or newer.
3. Clone this repository:

   git clone https://github.com/geunil748-dev/auto_trading.git C:\auto_trading
   cd C:\auto_trading

Basic setup
-----------
Run this once:

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1

Then open .env in Notepad and fill in MSSQL, KIS mock-account, and monitor
token values.

Initialize DB after editing .env
--------------------------------
   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -InitDb

Register auto-start tasks on a normal PC
----------------------------------------
   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow

Register auto-start tasks on AWS Windows as SYSTEM
--------------------------------------------------
Open PowerShell as Administrator, then run:

   powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup\setup_windows.ps1 -SkipInstall -RegisterTasks -RunAs System -ReplaceTasks -StartNow

Monitor URL
-----------
After services start, open:

   http://127.0.0.1:4174/

Important
---------
- Do not commit .env, token files, logs, or .venv.
- Disable sleep mode while the bot is running.
- On AWS, configure firewall/security group rules before connecting from a phone or another PC.
