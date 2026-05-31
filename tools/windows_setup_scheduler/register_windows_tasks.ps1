param(
    [string]$Workspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$PythonPath = "",
    [string]$TaskPrefix = "AutoTrading",
    [ValidateSet("CurrentUser", "System")]
    [string]$RunAs = "CurrentUser",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

# 전용 노트북에서 자동매매 작업 스케줄러를 등록합니다.
# 콘솔 창이 뜨지 않도록 작업 스케줄러는 wscript 숨김 런처를 실행합니다.

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

    # powershell.exe를 직접 실행하면 창이 순간적으로 보일 수 있습니다.
    # wscript.exe가 VBS 런처를 숨김 모드로 실행하게 해서 시작 창 노출을 막습니다.
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$ScriptPath`" `"$PythonPath`""
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
    $settings.Hidden = $true

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
$monitorScript = Join-Path $workspacePath "tools\start_monitor_server_hidden.vbs"
$schedulerScript = Join-Path $workspacePath "tools\start_scheduler_hidden.vbs"

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
