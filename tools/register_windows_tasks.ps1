param(
    [string]$Workspace = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [string]$TaskPrefix = "AutoTrading",
    [ValidateSet("CurrentUser", "System")]
    [string]$RunAs = "CurrentUser",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

# Register Windows scheduled tasks on a dedicated laptop or AWS Windows server.
# This only registers tasks; the actual services are started by the launcher scripts.

function Resolve-PythonPath {
    param(
        [string]$WorkspacePath,
        [string]$RequestedPython
    )

    if ($RequestedPython) {
        return $RequestedPython
    }

    $venvPython = Join-Path $WorkspacePath ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    return "python"
}

function Register-AutoTradingTask {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [string]$PythonPath,
        [string]$WorkspacePath,
        [string]$RunAsMode
    )

    if ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and -not $Replace) {
        Write-Host "$TaskName already exists. Use -Replace to recreate it."
        return
    }

    if ($Replace) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }

    # The task runs this PowerShell command.
    # Passing Python through an environment variable keeps the source portable.
    $argument = @(
        "-NoProfile",
        "-ExecutionPolicy Bypass",
        "-WindowStyle Hidden",
        "-Command `"& { `$env:AUTO_TRADING_PYTHON='$PythonPath'; Set-Location -LiteralPath '$WorkspacePath'; & '$ScriptPath' }`""
    ) -join " "

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
    if ($RunAsMode -eq "System") {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    }
    else {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    }
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Auto trading service task for $TaskName" | Out-Null

    Write-Host "$TaskName registered."
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$resolvedPython = Resolve-PythonPath -WorkspacePath $workspacePath -RequestedPython $PythonPath
$monitorScript = Join-Path $workspacePath "tools\start_monitor_server.ps1"
$schedulerScript = Join-Path $workspacePath "tools\start_scheduler.ps1"

if (-not (Test-Path -LiteralPath $monitorScript)) {
    throw "Monitor script not found: $monitorScript"
}
if (-not (Test-Path -LiteralPath $schedulerScript)) {
    throw "Scheduler script not found: $schedulerScript"
}

Register-AutoTradingTask `
    -TaskName "$TaskPrefix-Monitor" `
    -ScriptPath $monitorScript `
    -PythonPath $resolvedPython `
    -WorkspacePath $workspacePath `
    -RunAsMode $RunAs

Register-AutoTradingTask `
    -TaskName "$TaskPrefix-Scheduler" `
    -ScriptPath $schedulerScript `
    -PythonPath $resolvedPython `
    -WorkspacePath $workspacePath `
    -RunAsMode $RunAs

Write-Host "Done. Python: $resolvedPython"
Write-Host "RunAs: $RunAs"
Write-Host "To run now, use: Start-ScheduledTask -TaskName '$TaskPrefix-Monitor'; Start-ScheduledTask -TaskName '$TaskPrefix-Scheduler'"
