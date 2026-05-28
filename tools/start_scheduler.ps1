$workspace = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$logDir = Join-Path $workspace "logs"
$logPath = Join-Path $logDir "startup-scheduler.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-StartupLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

# Windows PowerShell 5 reads UTF-8 without BOM inconsistently, so log text stays ASCII.
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\AutoTradingScheduler", [ref]$createdNew)
if (-not $createdNew) {
    Write-StartupLog "scheduler launcher already running; exiting"
    return
}

Start-Sleep -Seconds 20

try {
    while ($true) {
        try {
            Set-Location -LiteralPath $workspace
            $env:PYTHONPATH = Join-Path $workspace "src"

            Write-StartupLog "scheduler starting"
            & $python -m trading_bot run-scheduler --monitor-state "monitor/state.json" 2>&1 |
                ForEach-Object { Write-StartupLog $_.ToString() }

            Write-StartupLog "scheduler exited: $LASTEXITCODE"
        }
        catch {
            Write-StartupLog "scheduler start error: $($_.Exception.Message)"
        }

        Start-Sleep -Seconds 15
    }
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
