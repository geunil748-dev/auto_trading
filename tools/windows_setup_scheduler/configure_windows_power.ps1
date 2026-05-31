param(
    [switch]$SkipHibernateOff
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-PowerCfg {
    param([string[]]$Arguments)

    & powercfg.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "powercfg failed: powercfg $($Arguments -join ' ')"
    }
}

if (-not (Test-IsAdministrator)) {
    throw "Open PowerShell as Administrator and run this script again."
}

Write-Host "Configuring this Windows notebook to stay awake for local server operation..."

# Disable sleep on AC and battery. Display timeout is left to the user's preference.
Invoke-PowerCfg -Arguments @("/change", "standby-timeout-ac", "0")
Invoke-PowerCfg -Arguments @("/change", "standby-timeout-dc", "0")
Invoke-PowerCfg -Arguments @("/change", "hibernate-timeout-ac", "0")
Invoke-PowerCfg -Arguments @("/change", "hibernate-timeout-dc", "0")

# Lid close action: 0 = do nothing. This keeps Windows running with the lid closed.
Invoke-PowerCfg -Arguments @("/setacvalueindex", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION", "0")
Invoke-PowerCfg -Arguments @("/setdcvalueindex", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION", "0")

if (-not $SkipHibernateOff) {
    Invoke-PowerCfg -Arguments @("/hibernate", "off")
}

Invoke-PowerCfg -Arguments @("/setactive", "SCHEME_CURRENT")

Write-Host "Done. Sleep is disabled and lid close is set to do nothing."
Write-Host "Keep the notebook connected to power while auto_trading is running."
