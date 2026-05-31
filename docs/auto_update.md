# Automatic Server Update

This guide enables the Windows 11 Home server notebook to detect changes on `origin/main` and update itself without manual deployment.

The server notebook remains a read-only runtime node:

- Development happens on the main PC or Codex.
- The server notebook tracks only `main`.
- The server notebook must not contain local code edits.
- Real-trading safety defaults stay closed: `REAL_TRADING_ENABLED=false` and `REAL_EMERGENCY_STOP=true`.

## How It Works

The Windows scheduled task `AutoTrading-AutoUpdate` runs every five minutes.

Each run:

1. Checks that the working tree has no local changes.
2. Runs `git fetch origin main`.
3. Compares local `HEAD` with `origin/main`.
4. Exits immediately when no changes are detected.
5. Verifies the update is fast-forward only.
6. Runs `git pull --ff-only origin main`.
7. Runs `tools/windows_setup_scheduler/update_local_server.ps1 -SkipPull`.
8. Refreshes packages and runs `preflight`.
9. Restarts Monitor and Scheduler only after the update and preflight succeed.

## Register The Scheduled Task

Run this on the server notebook after the first manual setup has already passed `preflight`:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\register_auto_update_task.ps1 -Replace -StartNow
```

The task runs every five minutes by default. To use another interval:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\register_auto_update_task.ps1 -Replace -IntervalMinutes 10
```

## Logs

Automatic update logs are written to:

```text
C:\auto_trading\logs\auto_update.log
```

Typical no-change log:

```text
[2026-06-01 10:00:00]
No changes detected
```

Typical update log:

```text
[2026-06-01 10:05:00]
Changes detected
Running git pull --ff-only

[2026-06-01 10:05:00]
Running update_local_server.ps1

[2026-06-01 10:05:00]
Update completed successfully
```

Typical failure log:

```text
[2026-06-01 10:05:00]
Update failed
Error: Local changes detected. This server clone must stay read-only.
```

## Failure Behavior

- Local changes: update stops before fetch/pull changes are applied.
- Non-fast-forward state: update stops and requires manual intervention.
- `git pull --ff-only` failure: update stops.
- Package refresh failure: Monitor and Scheduler are not restarted.
- `preflight` failure: Monitor and Scheduler are not restarted.
- Restart failure: error is logged and the task exits with failure.

## Rollback

Rollback is intentionally manual.

1. Revert or fix the bad change on the development PC.
2. Push the fix to `main`.
3. Wait for the next five-minute auto-update run, or run:

```powershell
cd C:\auto_trading
powershell.exe -ExecutionPolicy Bypass -File .\tools\windows_setup_scheduler\auto_update.ps1
```

For an emergency pause:

```powershell
Disable-ScheduledTask -TaskName AutoTrading-AutoUpdate
```

Re-enable it with:

```powershell
Enable-ScheduledTask -TaskName AutoTrading-AutoUpdate
```
