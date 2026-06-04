$workspace = Split-Path -Parent $PSScriptRoot
$utf8ConsoleScript = Join-Path $workspace "scripts\Set-Utf8Console.ps1"
if (Test-Path -LiteralPath $utf8ConsoleScript) {
    . $utf8ConsoleScript -Quiet
}

$venvPython = Join-Path $workspace ".venv\Scripts\python.exe"

function Test-PythonModules {
    param(
        [string]$PythonPath,
        [string[]]$Modules
    )

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    $script = "import importlib.util, sys; missing=[name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]; raise SystemExit(1 if missing else 0)"
    & $PythonPath -c $script @Modules *> $null
    return $LASTEXITCODE -eq 0
}

$python = if ($env:AUTO_TRADING_PYTHON) {
    $env:AUTO_TRADING_PYTHON
}
else {
    $venvPython
}
$requiredModules = @("dotenv", "pyodbc", "clr", "yfinance", "tzdata")
$logDir = Join-Path $workspace "logs"
$logPath = Join-Path $logDir "startup-monitor.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-StartupLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message" -ErrorAction Stop
    }
    catch {
        # Keep running even when startup log writes fail.
    }
}

# Windows PowerShell 5 reads UTF-8 without BOM inconsistently, so log text stays ASCII.
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\AutoTradingMonitorServer", [ref]$createdNew)
if (-not $createdNew) {
    Write-StartupLog "monitor server launcher already running; exiting"
    return
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-StartupLog "monitor server startup blocked: python executable missing: $python"
    return
}
if (-not (Test-PythonModules -PythonPath $python -Modules $requiredModules)) {
    Write-StartupLog "monitor server startup blocked: missing required Python modules"
    return
}

Start-Sleep -Seconds 20

try {
    while ($true) {
        try {
            Set-Location -LiteralPath $workspace
            $env:PYTHONPATH = Join-Path $workspace "src"

            Write-StartupLog "monitor server python: $python"
            Write-StartupLog "monitor server starting"
            & $python -m trading_bot serve-monitor --host 0.0.0.0 --port 4174 2>&1 |
                ForEach-Object { Write-StartupLog $_.ToString() }

            Write-StartupLog "monitor server exited: $LASTEXITCODE"
        }
        catch {
            Write-StartupLog "monitor server start error: $($_.Exception.Message)"
        }

        Start-Sleep -Seconds 15
    }
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
