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

function Resolve-PythonPath {
    param([string]$PythonPath)

    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        return $null
    }
    $candidate = $PythonPath.Trim().Trim('"')
    if (Test-Path -LiteralPath $candidate) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $candidate
}

function Get-QuotedArguments {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return @()
    }
    return [regex]::Matches($Text, '"([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value }
}

function Get-ServicePythonFromScheduledTasks {
    $paths = @()
    foreach ($taskName in @("AutoTrading-Monitor", "AutoTrading-Scheduler")) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $task) {
            continue
        }
        foreach ($action in $task.Actions) {
            foreach ($argument in Get-QuotedArguments $action.Arguments) {
                if ([IO.Path]::GetFileName($argument) -ieq "python.exe") {
                    $paths += Resolve-PythonPath $argument
                }
            }
        }
    }
    $uniquePaths = @($paths | Where-Object { $_ } | Sort-Object -Unique)
    if ($uniquePaths.Count -gt 1) {
        throw "Scheduled tasks use different Python runtimes: $($uniquePaths -join ', ')"
    }
    if ($uniquePaths.Count -eq 1) {
        return $uniquePaths[0]
    }
    return $null
}

function Get-ServicePythonFromRunningProcesses {
    $paths = @()
    $servicePattern = "(^|\s)-m\s+trading_bot\s+(serve-monitor|run-scheduler)(\s|$)"
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $servicePattern
        }
    foreach ($process in $processes) {
        if ($process.CommandLine -match '^"([^"]*python\.exe)"\s+-m\s+trading_bot\s+') {
            $paths += Resolve-PythonPath $Matches[1]
        }
        elseif ($process.CommandLine -match '^(\S*python\.exe)\s+-m\s+trading_bot\s+') {
            $paths += Resolve-PythonPath $Matches[1]
        }
    }
    $uniquePaths = @($paths | Where-Object { $_ } | Sort-Object -Unique)
    if ($uniquePaths.Count -gt 1) {
        throw "Running services use different Python runtimes: $($uniquePaths -join ', ')"
    }
    if ($uniquePaths.Count -eq 1) {
        return $uniquePaths[0]
    }
    return $null
}

function Resolve-DeployPython {
    param(
        [string]$VenvPython,
        [string]$DefaultPython
    )

    $servicePython = Get-ServicePythonFromScheduledTasks
    $runningPython = Get-ServicePythonFromRunningProcesses
    if ($servicePython -and $runningPython -and $servicePython -ne $runningPython) {
        throw "Scheduled task Python and running service Python differ: $servicePython / $runningPython"
    }
    if ($servicePython) {
        return $servicePython
    }
    if ($runningPython) {
        return $runningPython
    }

    foreach ($envName in @("DEPLOY_PYTHON", "AUTOTRADING_PYTHON", "AUTO_TRADING_PYTHON")) {
        $value = [Environment]::GetEnvironmentVariable($envName, "Process")
        if ($value) {
            return Resolve-PythonPath $value
        }
    }
    if (Test-Path -LiteralPath $DefaultPython) {
        return (Resolve-Path -LiteralPath $DefaultPython).Path
    }
    if (Test-Path -LiteralPath $VenvPython) {
        return (Resolve-Path -LiteralPath $VenvPython).Path
    }
    throw "No Python runtime was found for deployment preflight."
}

function Test-PythonImport {
    param(
        [string]$PythonPath,
        [string]$ModuleName
    )

    $output = & $PythonPath -c "import $ModuleName; print('ok')" 2>&1
    return [pscustomobject]@{
        Module = $ModuleName
        Ok = ($LASTEXITCODE -eq 0)
        Output = (($output | ForEach-Object { $_.ToString() }) -join "`n")
    }
}

function Invoke-PythonEnvironmentCheck {
    param([string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Selected Python was not found: $PythonPath"
    }
    Write-Host "Preflight Python: $PythonPath"
    $versionOutput = & $PythonPath --version 2>&1
    $versionText = ($versionOutput | ForEach-Object { $_.ToString() }) -join "`n"
    Write-Host "Preflight Python version: $versionText"
    if ($LASTEXITCODE -ne 0) {
        throw "Selected Python failed to report version: $PythonPath"
    }

    foreach ($moduleName in @("clr", "pyodbc")) {
        $result = Test-PythonImport -PythonPath $PythonPath -ModuleName $moduleName
        $status = if ($result.Ok) { "OK" } else { "FAIL" }
        Write-Host "Python import ${moduleName}: $status"
        if (-not $result.Ok) {
            throw "Selected Python cannot import $moduleName. Python: $PythonPath. Output: $($result.Output)"
        }
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
        Invoke-PythonEnvironmentCheck -PythonPath $PythonPath
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
$defaultPython = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

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
    Write-Step "Run preflight"
    $env:PYTHONPATH = Join-Path $workspacePath "src"
    $deployPython = Resolve-DeployPython -VenvPython $venvPython -DefaultPython $defaultPython
    Invoke-Preflight -PythonPath $deployPython -WorkingDirectory $workspacePath
}

if (-not $SkipRestart) {
    Write-Step "Stop running services"
    Stop-AutoTradingProcess -WorkspacePath $workspacePath

    Write-Step "Start scheduled tasks"
    Start-AutoTradingTasks
}

Write-Step "Done"
Write-Host "Updated $Branch and restarted local auto_trading services."
