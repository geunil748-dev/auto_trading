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

function Invoke-Preflight {
    param(
        [string]$PythonPath,
        [string]$WorkingDirectory
    )

    $previousLocation = Get-Location
    try {
        Set-Location -LiteralPath $WorkingDirectory
        $preflightOutput = & $PythonPath -m trading_bot preflight 2>&1
        $exitCode = $LASTEXITCODE
        $preflightText = ($preflightOutput | ForEach-Object { $_.ToString() }) -join "`n"
        if ($preflightText) {
            Write-Host $preflightText
        }

        try {
            $preflight = $preflightText | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Preflight output was not valid JSON. Exit code: $exitCode"
        }

        $failedChecks = @()
        if ($preflight.mssql.connected -ne $true) {
            $failedChecks += "mssql.connected"
        }
        if ($preflight.mssql.required_tables_ready -ne $true) {
            $failedChecks += "mssql.required_tables_ready"
        }
        if ($preflight.mssql.required_columns_ready -ne $true) {
            $failedChecks += "mssql.required_columns_ready"
        }

        if ($failedChecks.Count -gt 0) {
            throw "Preflight readiness failed: $($failedChecks -join ', ')"
        }
        if ($exitCode -ne 0) {
            throw "Preflight command failed with exit code $exitCode"
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
    $servicePattern = "(^|\s)-m\s+trading_bot\s+(serve-monitor|run-scheduler)(\s|$)"
    $allProcesses = Get-CimInstance Win32_Process
    $serviceProcesses = $allProcesses |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $servicePattern
        }
    $launcherProcesses = $allProcesses |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $scriptPattern -and
            $_.CommandLine -match $escapedWorkspace
        }

    $seen = @{}
    foreach ($process in @($serviceProcesses + $launcherProcesses)) {
        if ($seen.ContainsKey($process.ProcessId)) {
            continue
        }
        $seen[$process.ProcessId] = $true
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
    Invoke-Preflight -PythonPath $venvPython -WorkingDirectory $workspacePath
}

if (-not $SkipRestart) {
    Write-Step "Stop running services"
    Stop-AutoTradingProcess -WorkspacePath $workspacePath

    Write-Step "Start scheduled tasks"
    Start-AutoTradingTasks
}

Write-Step "Done"
Write-Host "Updated $Branch and restarted local auto_trading services."
