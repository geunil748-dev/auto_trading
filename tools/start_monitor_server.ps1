$workspace = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$logDir = Join-Path $workspace "logs"
$logPath = Join-Path $logDir "startup-monitor.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-StartupLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

# Windows PowerShell 5 reads UTF-8 without BOM inconsistently, so log text stays ASCII.
Start-Sleep -Seconds 20

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
