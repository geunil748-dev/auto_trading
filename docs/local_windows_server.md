# Local Windows 11 Server Setup

This guide runs `auto_trading` on a personal Windows 11 Home notebook as a 24-hour server instead of AWS EC2.

The trading logic is unchanged. The default real-trading safety values stay closed:

```env
REAL_TRADING_ENABLED=false
REAL_EMERGENCY_STOP=true
```

## 1. Prepare the Notebook

Use a dedicated Windows account if possible, connect stable power, and keep the notebook on a reliable network.

After cloning the repository, open PowerShell as Administrator and run:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\configure_windows_power.ps1
```

The script disables sleep and hibernation and keeps the notebook running when the lid is closed. The display may still turn off; the important part is that Windows must not sleep.

## 2. Install Git and Python

Install these first:

- Git for Windows
- Python 3.11 or newer, with `python` or `py` available in PATH

After cloning the repository in the next step, check both tools:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\check_windows_prereqs.ps1
```

If the script reports a missing tool, install it and reopen PowerShell.

## 3. Clone the Repository

```powershell
git clone https://github.com/geunil748-dev/auto_trading.git C:\auto_trading
cd C:\auto_trading
```

## 4. Create `.env` and Install Packages

Run the existing Windows setup script:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1
```

This keeps the existing first-run flow:

- Copies `.env.example` to `.env` if `.env` does not exist
- Creates `.venv`
- Installs Python packages

Open `.env` locally and fill only the values needed for your environment, such as MSSQL, KIS mock-trading credentials, and `MONITOR_BEARER_TOKEN`. Do not commit `.env`.

## 5. Confirm Safety Defaults

Before running unattended, confirm these lines remain in `.env` unless you are deliberately doing a separate real-trading rollout:

```env
REAL_TRADING_ENABLED=false
REAL_EMERGENCY_STOP=true
```

With these defaults, real-account order submission remains blocked.

## 6. Initialize the Database

After `.env` is filled, initialize MSSQL tables if needed:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -InitDb
```

## 7. Register Monitor and Scheduler

Reuse the existing task registration flow:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow
```

This registers:

- `AutoTrading-Monitor`: monitor web server on port `4174`
- `AutoTrading-Scheduler`: trading scheduler timeline

On Windows 11 Home this uses the current user logon trigger. Keep the user signed in after reboot, or sign in once so the tasks can start.

## 8. Verify Operation

Open the monitor on the notebook:

```text
http://127.0.0.1:4174/
```

From another device on the same Wi-Fi, replace `127.0.0.1` with the notebook's local IP address:

```text
http://192.168.0.7:4174/
```

Check scheduled tasks:

```powershell
Get-ScheduledTask -TaskName AutoTrading-Monitor,AutoTrading-Scheduler
Get-ScheduledTaskInfo -TaskName AutoTrading-Monitor
Get-ScheduledTaskInfo -TaskName AutoTrading-Scheduler
```

Check startup logs:

```powershell
Get-Content .\logs\startup-monitor.log -Tail 50
Get-Content .\logs\startup-scheduler.log -Tail 50
```

## 9. Files That Must Stay Local

Do not commit secrets or runtime output. The repository ignores these paths and patterns:

- `.env`
- `.env.*`, except `.env.example`
- `.kis-token.json` and `.kis-token-*.json`
- `logs/` and `*.log`
- `.venv/`
- monitor runtime state and reports

If a file contains account numbers, API keys, bearer tokens, access tokens, or generated logs, keep it local.

## 10. Daily Operating Notes

Keep the notebook connected to power. Windows Update may reboot the machine, so check the monitor after updates. If the notebook reboots, sign in to Windows so the current-user scheduled tasks can start.

For a true boot-without-login setup, use Windows Pro or Windows Server and register tasks with `-RunAs System` from an Administrator PowerShell. Windows 11 Home is best treated as a signed-in local server.
