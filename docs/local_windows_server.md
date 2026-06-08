# Local Windows 11 Server Setup

This guide runs `auto_trading` on a personal Windows 11 Home notebook as a 24-hour local server. Development happens on the main PC; the server notebook only pulls from GitHub and runs the services.

The trading logic is unchanged. The default real-trading safety values stay closed:

```env
REAL_TRADING_ENABLED=false
REAL_EMERGENCY_STOP=true
```

## 1. Prepare the Notebook

Use a dedicated Windows account if possible, connect stable power, and keep the notebook on a reliable network.

Open PowerShell as Administrator and run:

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

`init-db`, `preflight`, and `repair-db-schema` have separate roles. `preflight`
is read-only, `repair-db-schema` is an explicit safe repair command, and
`init-db` is for first-time schema setup. See
[db_migration_repair.md](db_migration_repair.md) before running repair or init
commands on an operating server.

## 7. Register Monitor and Scheduler

Reuse the existing task registration flow:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow
```

This registers:

- `AutoTrading-Monitor`: monitor web server on port `4174`
- `AutoTrading-Scheduler`: trading scheduler timeline

On Windows 11 Home this uses the current user logon trigger. Keep the user signed in after reboot, or sign in once so the tasks can start.

## 8. Pull Updates and Restart Services

After code is pushed from the main PC and merged into `main`, update the server notebook with:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\update_local_server.ps1
```

The script refuses to continue if the server clone has local code changes. It then fast-forward pulls `main`, refreshes Python packages, runs `preflight`, stops existing Monitor/Scheduler launcher processes, and starts the scheduled tasks again.

Use this shorter command only when you deliberately want to skip package refresh and preflight:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\update_local_server.ps1 -SkipInstall -SkipPreflight
```

For a monitor-only restart after static file or `monitor_server.py` changes,
stop and start the monitor launcher directly:

```powershell
.\tools\stop_monitor_server.ps1
.\tools\start_monitor_server.ps1
```

The stop script targets the monitor launcher and `trading_bot serve-monitor`
processes for port `4174`. It does not stop the scheduler. If scheduler code or
settings did not change, a scheduler restart is not required.

## 9. Verify Operation

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

Check monitor APIs from the server. `/health` is public enough for readiness
checks, but `/api/state` requires a bearer header when `MONITOR_BEARER_TOKEN`
is configured:

```powershell
curl.exe http://localhost:4174/health
curl.exe http://localhost:4174/api/state
curl.exe -H "Authorization: Bearer <MONITOR_BEARER_TOKEN>" http://localhost:4174/api/state
```

Keep the real monitor bearer token out of logs, chat messages, screenshots, and
committed files. Use `<MONITOR_BEARER_TOKEN>` only as a placeholder in
documentation.

## 10. Files That Must Stay Local

Do not commit secrets or runtime output. The repository ignores these paths and patterns:

- `.env`
- `.env.*`, except `.env.example`
- `.kis-token.json` and `.kis-token-*.json`
- `logs/` and `*.log`
- `.venv/`
- monitor runtime state and reports

If a file contains account numbers, API keys, bearer tokens, access tokens, or generated logs, keep it local.

## 11. Daily Operating Notes

Keep the notebook connected to power. Windows Update may reboot the machine, so check the monitor after updates. If the notebook reboots, sign in to Windows so the current-user scheduled tasks can start.

Windows 11 Home is best treated as a signed-in local server. AWS, Windows Server, and `-RunAs System` procedures are not needed for this notebook setup.

## Minimal Command Sequence

Use this sequence on a fresh server notebook:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\check_windows_prereqs.ps1
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\configure_windows_power.ps1
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1
notepad .env
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -InitDb
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m trading_bot preflight
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\setup_windows.ps1 -SkipInstall -RegisterTasks -ReplaceTasks -StartNow
```

Use this sequence for later updates:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\update_local_server.ps1
```

## Pre-Operation Checklist

- Windows sleep is disabled and lid close is set to do nothing.
- The notebook is connected to stable power and network.
- Git and Python 3.11+ pass `check_windows_prereqs.ps1`.
- `.env` exists locally and is not committed.
- `REAL_TRADING_ENABLED=false`.
- `REAL_EMERGENCY_STOP=true`.
- KIS credentials are mock-trading credentials unless a separate real-trading rollout is planned.
- MSSQL connection works and DB initialization has completed.
- `preflight` passes.
- `AutoTrading-Monitor` and `AutoTrading-Scheduler` are registered.
- Monitor opens at `http://127.0.0.1:4174/`.
- `logs/startup-monitor.log` and `logs/startup-scheduler.log` show recent starts without repeated errors.
- Windows Update active hours are set so surprise reboots are less likely during market hours.
