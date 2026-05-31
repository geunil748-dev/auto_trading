param(
    [string]$Workspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "AutoTrading-AutoUpdate",
    [int]$IntervalMinutes = 5,
    [switch]$Replace,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$autoUpdateScript = Join-Path $workspacePath "tools\windows_setup_scheduler\auto_update.ps1"

if (-not (Test-Path -LiteralPath $autoUpdateScript)) {
    throw "Auto update script not found: $autoUpdateScript"
}

if ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and -not $Replace) {
    Write-Host "$TaskName already exists. Use -Replace to recreate it."
    return
}

if ($Replace) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$autoUpdateScript`" -Workspace `"$workspacePath`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
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
    -Description "Checks origin/main every $IntervalMinutes minutes and runs auto_trading local server update when changed." | Out-Null

Write-Host "$TaskName registered."
Write-Host "Interval minutes: $IntervalMinutes"
Write-Host "Log: $(Join-Path $workspacePath 'logs\auto_update.log')"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "$TaskName started."
}
