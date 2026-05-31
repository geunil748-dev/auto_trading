param(
    [string]$Workspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Branch = "main",
    [switch]$SkipInstall,
    [switch]$SkipPreflight,
    [switch]$SkipPull,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Invoke-Checked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $previousLocation = Get-Location
    try {
        if ($WorkingDirectory) {
            Set-Location -LiteralPath $WorkingDirectory
        }
        & $Exe @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed: $Exe $($ArgumentList -join ' ')"
        }
    }
    finally {
        Set-Location -LiteralPath $previousLocation
    }
}

function Stop-AutoTradingProcess {
    param([string]$WorkspacePath)

    $escapedWorkspace = [regex]::Escape($WorkspacePath)
    $scriptPattern = "start_(monitor_server|scheduler)\.ps1"
    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $scriptPattern -and
            $_.CommandLine -match $escapedWorkspace
        }

    foreach ($process in $processes) {
        Write-Host "Stopping process $($process.ProcessId): $($process.Name)"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-AutoTradingTasks {
    $taskNames = @("AutoTrading-Monitor", "AutoTrading-Scheduler")
    foreach ($taskName in $taskNames) {
        if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
            throw "Scheduled task was not found: $taskName. Register tasks before running this update script."
        }
        Start-ScheduledTask -TaskName $taskName
        Write-Host "Started $taskName"
    }
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$venvPython = Join-Path $workspacePath ".venv\Scripts\python.exe"

Write-Step "Workspace"
Write-Host $workspacePath

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH. Install Git for Windows and reopen PowerShell."
}

if (-not (Test-Path -LiteralPath (Join-Path $workspacePath ".git"))) {
    throw "Workspace is not a Git repository: $workspacePath"
}

$dirty = git -C $workspacePath status --porcelain
if ($dirty) {
    throw "Local changes detected. This server clone should stay read-only; commit, stash, or reset changes before updating."
}

if (-not $SkipPull) {
    Write-Step "Pull latest code"
    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "fetch", "origin", $Branch) -WorkingDirectory $workspacePath
    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "checkout", $Branch) -WorkingDirectory $workspacePath
    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "pull", "--ff-only", "origin", $Branch) -WorkingDirectory $workspacePath
}

if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Virtual environment was not found: $venvPython. Run setup_windows.ps1 first."
    }

    Write-Step "Refresh Python packages"
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "pip", "install", "-e", ".[integrations]") -WorkingDirectory $workspacePath
}

if (-not $SkipPreflight) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Virtual environment was not found: $venvPython. Run setup_windows.ps1 first."
    }

    Write-Step "Run preflight"
    $env:PYTHONPATH = Join-Path $workspacePath "src"
    Invoke-Checked -Exe $venvPython -ArgumentList @("-m", "trading_bot", "preflight") -WorkingDirectory $workspacePath
}

if (-not $SkipRestart) {
    Write-Step "Stop running services"
    Stop-AutoTradingProcess -WorkspacePath $workspacePath

    Write-Step "Start scheduled tasks"
    Start-AutoTradingTasks
}

Write-Step "Done"
Write-Host "Updated $Branch and restarted local auto_trading services."
