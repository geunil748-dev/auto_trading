[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int]$Port = 4174,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$utf8ConsoleScript = Join-Path $workspace "scripts\Set-Utf8Console.ps1"
if (Test-Path -LiteralPath $utf8ConsoleScript) {
    . $utf8ConsoleScript -Quiet
}

$logDir = Join-Path $workspace "logs"
$logPath = Join-Path $logDir "stop-monitor.log"
if (-not $WhatIfPreference) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

function Write-StopLog {
    param([string]$Message)

    if ($WhatIfPreference) {
        return
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message" -ErrorAction Stop
    }
    catch {
        # Keep stopping even when stop log writes fail.
    }
}

function Get-CommandLineProcesses {
    $previousWhatIfPreference = $WhatIfPreference
    try {
        $WhatIfPreference = $false
        return @(Get-CimInstance Win32_Process -ErrorAction Stop)
    }
    catch {
        try {
            $WhatIfPreference = $false
            return @(Get-WmiObject Win32_Process -ErrorAction Stop)
        }
        catch {
            Write-StopLog "process query failed: $($_.Exception.GetType().Name)"
            return @()
        }
    }
    finally {
        $WhatIfPreference = $previousWhatIfPreference
    }
}

function Test-IsSchedulerProcess {
    param([string]$CommandLine)

    $text = [string]$CommandLine
    return (
        $text -match "start_scheduler\.ps1" -or
        $text -match "start_scheduler\.cmd" -or
        $text -match "run-scheduler" -or
        $text -match "AutoTradingScheduler"
    )
}

function Test-IsMonitorLauncher {
    param([object]$Process)

    $commandLine = [string]$Process.CommandLine
    if (-not $commandLine) {
        return $false
    }
    if (Test-IsSchedulerProcess -CommandLine $commandLine) {
        return $false
    }
    return $commandLine -match "start_monitor_server\.ps1"
}

function Test-IsMonitorPython {
    param(
        [object]$Process,
        [int]$MonitorPort,
        [int[]]$ListenerPids
    )

    $commandLine = [string]$Process.CommandLine
    if (-not $commandLine) {
        return $false
    }
    if (Test-IsSchedulerProcess -CommandLine $commandLine) {
        return $false
    }
    if (-not ($commandLine -match "trading_bot" -and $commandLine -match "serve-monitor")) {
        return $false
    }

    $portPattern = "--port\s+$MonitorPort(\s|$)"
    return ($commandLine -match $portPattern -or $ListenerPids -contains [int]$Process.ProcessId)
}

function Get-ListenerPids {
    param([int]$MonitorPort)

    try {
        $pattern = "^\s*TCP\s+\S+:$MonitorPort\s+\S+\s+LISTENING\s+(\d+)"
        $pids = @(
            netstat.exe -ano |
                ForEach-Object {
                    if ($_ -match $pattern) {
                        [int]$Matches[1]
                    }
                } |
                Sort-Object -Unique
        )
        if ($pids.Count -gt 0) {
            return $pids
        }
    }
    catch {
        Write-StopLog "netstat listener query failed: $($_.Exception.GetType().Name)"
    }

    try {
        return @(
            Get-NetTCPConnection -LocalPort $MonitorPort -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    }
    catch {
        Write-StopLog "listener query failed: $($_.Exception.GetType().Name)"
        return @()
    }
}

function Select-UniqueProcess {
    param([object[]]$Processes)

    $seen = @{}
    $result = @()
    foreach ($process in $Processes) {
        $pidValue = [int]$process.ProcessId
        if ($pidValue -le 0 -or $seen.ContainsKey($pidValue)) {
            continue
        }
        $seen[$pidValue] = $true
        $result += $process
    }
    return $result
}

function Stop-ProcessSafe {
    param(
        [object]$Process,
        [string]$Reason
    )

    $pidValue = [int]$Process.ProcessId
    if ($pidValue -le 0) {
        return
    }

    Write-StopLog "stopping pid=$pidValue reason=$Reason"
    if ($PSCmdlet.ShouldProcess("pid=$pidValue", "Stop monitor process ($Reason)")) {
        try {
            if ($Force) {
                Stop-Process -Id $pidValue -Force -ErrorAction Stop
            }
            else {
                Stop-Process -Id $pidValue -ErrorAction Stop
            }
        }
        catch [System.ArgumentException] {
            Write-StopLog "process already stopped: pid=$pidValue"
        }
        catch {
            Write-StopLog "stop failed: pid=$pidValue error=$($_.Exception.GetType().Name)"
        }
    }
}

Write-StopLog "monitor stop requested port=$Port force=$($Force.IsPresent)"

$listenerPids = @(Get-ListenerPids -MonitorPort $Port)
$processes = @(Get-CommandLineProcesses)

$launcherProcesses = @(
    $processes | Where-Object { Test-IsMonitorLauncher -Process $_ }
)
$monitorProcesses = @(
    $processes | Where-Object {
        Test-IsMonitorPython -Process $_ -MonitorPort $Port -ListenerPids $listenerPids
    }
)
$listenerProcesses = @(
    foreach ($listenerPid in $listenerPids) {
        $processes | Where-Object {
            [int]$_.ProcessId -eq [int]$listenerPid -and
            (Test-IsMonitorPython -Process $_ -MonitorPort $Port -ListenerPids $listenerPids)
        }
    }
)

$launcherProcesses = Select-UniqueProcess -Processes $launcherProcesses
$monitorProcesses = Select-UniqueProcess -Processes $monitorProcesses
$listenerProcesses = Select-UniqueProcess -Processes $listenerProcesses

foreach ($process in $launcherProcesses) {
    Write-StopLog "monitor launcher process found: pid=$($process.ProcessId)"
}
foreach ($process in $monitorProcesses) {
    Write-StopLog "monitor python process found: pid=$($process.ProcessId)"
}
foreach ($pidValue in $listenerPids) {
    Write-StopLog "monitor listener found: port=$Port pid=$pidValue"
}

if ($launcherProcesses.Count -eq 0 -and $monitorProcesses.Count -eq 0 -and $listenerProcesses.Count -eq 0) {
    Write-StopLog "monitor process not found"
    Write-Output "monitor process not found"
    exit 0
}

foreach ($process in $launcherProcesses) {
    Stop-ProcessSafe -Process $process -Reason "launcher"
}

Start-Sleep -Seconds 2

$listenerPids = @(Get-ListenerPids -MonitorPort $Port)
$processes = @(Get-CommandLineProcesses)
$monitorProcesses = @(
    $processes | Where-Object {
        Test-IsMonitorPython -Process $_ -MonitorPort $Port -ListenerPids $listenerPids
    }
)
$monitorProcesses = Select-UniqueProcess -Processes $monitorProcesses

foreach ($process in $monitorProcesses) {
    Stop-ProcessSafe -Process $process -Reason "serve-monitor"
}

Start-Sleep -Seconds 2

$listenerPids = @(Get-ListenerPids -MonitorPort $Port)
if ($listenerPids.Count -gt 0 -and -not $WhatIfPreference) {
    $processes = @(Get-CommandLineProcesses)
    $listenerProcesses = @(
        foreach ($listenerPid in $listenerPids) {
            $processes | Where-Object {
                [int]$_.ProcessId -eq [int]$listenerPid -and
                (Test-IsMonitorPython -Process $_ -MonitorPort $Port -ListenerPids $listenerPids)
            }
        }
    )
    $listenerProcesses = Select-UniqueProcess -Processes $listenerProcesses
    foreach ($process in $listenerProcesses) {
        Stop-ProcessSafe -Process $process -Reason "port-listener"
    }
}

if ($WhatIfPreference) {
    Write-StopLog "monitor stop whatif completed"
    Write-Output "monitor stop whatif completed"
    exit 0
}

Start-Sleep -Seconds 1
$remainingListenerPids = @(Get-ListenerPids -MonitorPort $Port)
if ($remainingListenerPids.Count -gt 0) {
    Write-StopLog "monitor stop incomplete: remaining listener count=$($remainingListenerPids.Count)"
    Write-Output "monitor stop incomplete"
    exit 1
}

Write-StopLog "monitor stop completed"
Write-Output "monitor stop completed"
exit 0
