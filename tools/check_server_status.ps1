param(
    [string]$Workspace = (Split-Path -Parent $PSScriptRoot),
    [int]$MonitorPort = 4174
)

$ErrorActionPreference = "Stop"

function Write-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Message
    )

    $status = if ($Ok) { "PASS" } else { "FAIL" }
    Write-Host "$status $Name - $Message"
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$venvPython = Join-Path $workspacePath ".venv\Scripts\python.exe"

Write-Check -Name "Workspace" -Ok (Test-Path -LiteralPath $workspacePath) -Message $workspacePath
Write-Check -Name "VenvPython" -Ok (Test-Path -LiteralPath $venvPython) -Message $venvPython

if (Test-Path -LiteralPath $venvPython) {
    $version = (& $venvPython --version 2>$null) -join " "
    Write-Check -Name "PythonVersion" -Ok ($LASTEXITCODE -eq 0) -Message $version
}

$env:PYTHONPATH = Join-Path $workspacePath "src"
if (Test-Path -LiteralPath $venvPython) {
    Push-Location $workspacePath
    try {
        & $venvPython -m trading_bot preflight | Out-Null
        Write-Check -Name "Preflight" -Ok ($LASTEXITCODE -eq 0) -Message "trading_bot preflight"
    }
    finally {
        Pop-Location
    }
}

$healthUrl = "http://127.0.0.1:$MonitorPort/health"
try {
    $response = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 5
    Write-Check -Name "Health" -Ok ($response.StatusCode -eq 200) -Message $healthUrl
}
catch {
    Write-Check -Name "Health" -Ok $false -Message $_.Exception.Message
}

$listeners = @(netstat -ano | Select-String "LISTENING" | Select-String ":$MonitorPort")
Write-Check -Name "MonitorPort" -Ok ($listeners.Count -eq 1) -Message "port $MonitorPort listeners=$($listeners.Count)"
