param(
    [version]$MinimumPythonVersion = "3.11"
)

$ErrorActionPreference = "Stop"

function Write-Result {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Message
    )

    $mark = if ($Ok) { "[OK]" } else { "[FAIL]" }
    Write-Host "$mark $Name - $Message"
}

function Test-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Result -Name "Git" -Ok $false -Message "Git for Windows was not found in PATH."
        return $false
    }

    $versionText = (& git --version) -join " "
    Write-Result -Name "Git" -Ok $true -Message "$versionText ($($git.Source))"
    return $true
}

function Get-PythonVersion {
    param(
        [string]$Exe,
        [string[]]$Args
    )

    $versionScript = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    try {
        $output = & $Exe @Args -c $versionScript 2>$null
    }
    catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        return $null
    }

    return [version]($output | Select-Object -First 1)
}

function Test-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += @{ Exe = "py"; Args = @("-3.11"); Label = "py -3.11" }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += @{ Exe = "python"; Args = @(); Label = "python" }
    }

    foreach ($candidate in $candidates) {
        $foundVersion = Get-PythonVersion -Exe $candidate.Exe -Args $candidate.Args
        if ($foundVersion -and $foundVersion -ge $MinimumPythonVersion) {
            Write-Result -Name "Python" -Ok $true -Message "$($candidate.Label) version $foundVersion"
            return $true
        }
    }

    Write-Result -Name "Python" -Ok $false -Message "Python $MinimumPythonVersion or newer was not found in PATH."
    return $false
}

$gitOk = Test-Git
$pythonOk = Test-Python

if (-not ($gitOk -and $pythonOk)) {
    Write-Host ""
    Write-Host "Install Git for Windows and Python 3.11+, then open a new PowerShell window and retry."
    exit 1
}

Write-Host ""
Write-Host "All prerequisites are ready."
