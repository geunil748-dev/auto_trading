param(
    [string]$Workspace = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [switch]$SkipInstall,
    [switch]$InitDb,
    [switch]$RegisterTasks,
    [ValidateSet("CurrentUser", "System")]
    [string]$RunAs = "CurrentUser",
    [switch]$ReplaceTasks,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

# First-run setup script for a new Windows PC or AWS Windows server.
# Secrets are copied into .env locally and must never be committed.

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Resolve-BasePython {
    param([string]$RequestedPython)

    if ($RequestedPython) {
        if (Test-PythonCandidate -Exe $RequestedPython -ArgumentList @()) {
            return @{ Exe = $RequestedPython; Args = @() }
        }
        throw "Requested Python is not executable or is older than 3.11: $RequestedPython"
    }

    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PythonCandidate -Exe "py" -ArgumentList @("-3.11"))) {
        return @{ Exe = "py"; Args = @("-3.11") }
    }

    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-PythonCandidate -Exe "python" -ArgumentList @())) {
        return @{ Exe = "python"; Args = @() }
    }

    throw "Python 3.11 or newer was not found. Install Python or pass -PythonPath."
}

function Test-PythonCandidate {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )

    $testArgs = $ArgumentList + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
    & $Exe @testArgs *> $null
    return $LASTEXITCODE -eq 0
}

function Invoke-Checked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )

    & $Exe @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Exe $($ArgumentList -join ' ')"
    }
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$envExamplePath = Join-Path $workspacePath ".env.example"
$envPath = Join-Path $workspacePath ".env"
$venvPath = Join-Path $workspacePath ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

Write-Step "Workspace"
Write-Host $workspacePath

if (-not (Test-Path -LiteralPath $envExamplePath)) {
    throw ".env.example was not found: $envExamplePath"
}

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath
    Write-Host ".env was created. Fill API keys and DB settings before live use."
}
else {
    Write-Host ".env already exists; keeping it."
}

$basePython = Resolve-BasePython -RequestedPython $PythonPath

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Step "Create Python virtual environment"
    Invoke-Checked -Exe $basePython.Exe -ArgumentList ($basePython.Args + @("-m", "venv", $venvPath))
}
else {
    Write-Host "Using existing virtual environment: $venvPath"
}

if (-not $SkipInstall) {
    Write-Step "Install Python packages"
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "pip", "install", "-e", ".[integrations]")
}

if ($InitDb) {
    Write-Step "Initialize MSSQL schema"
    Push-Location $workspacePath
    try {
        $env:PYTHONPATH = Join-Path $workspacePath "src"
        Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "trading_bot", "init-db")
    }
    finally {
        Pop-Location
    }
}

if ($RegisterTasks) {
    Write-Step "Register Windows scheduled tasks"
    $taskArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $workspacePath "tools\register_windows_tasks.ps1"),
        "-Workspace", $workspacePath,
        "-PythonPath", $venvPython,
        "-RunAs", $RunAs
    )
    if ($ReplaceTasks) {
        $taskArgs += "-Replace"
    }
    Invoke-Checked -Exe "powershell.exe" -ArgumentList $taskArgs
}

if ($StartNow) {
    Write-Step "Start services now"
    if ($RegisterTasks) {
        Start-ScheduledTask -TaskName "AutoTrading-Monitor"
        Start-ScheduledTask -TaskName "AutoTrading-Scheduler"
    }
    else {
        Start-Process -WindowStyle Hidden -FilePath (Join-Path $workspacePath "tools\start_monitor_server.cmd")
        Start-Process -WindowStyle Hidden -FilePath (Join-Path $workspacePath "tools\start_scheduler.cmd")
    }
}

Write-Step "Done"
Write-Host "Monitor URL: http://127.0.0.1:4174/"
Write-Host "Next check: .\.venv\Scripts\python.exe -m trading_bot preflight"
