$workspace = Split-Path -Parent $PSScriptRoot
$defaultPython = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
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
elseif (Test-PythonModules -PythonPath $venvPython -Modules @("pyodbc", "yfinance", "tzdata")) {
    $venvPython
}
elseif (Test-Path -LiteralPath $defaultPython) {
    $defaultPython
}
else {
    "python"
}
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
        # 로그 파일 권한이나 잠금 문제가 있어도 모니터 서버 실행 자체는 계속 진행한다.
    }
}

# Windows PowerShell 5 reads UTF-8 without BOM inconsistently, so log text stays ASCII.
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\AutoTradingMonitorServer", [ref]$createdNew)
if (-not $createdNew) {
    Write-StartupLog "monitor server launcher already running; exiting"
    return
}

Start-Sleep -Seconds 20

try {
    while ($true) {
        try {
            Set-Location -LiteralPath $workspace
            $env:PYTHONPATH = Join-Path $workspace "src"

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
