$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $scriptDir
$setupScript = Join-Path $scriptDir "Set-Utf8Console.ps1"
$venvPython = Join-Path $workspace ".venv\Scripts\python.exe"
$testText = -join @(
    [char]0xD55C, [char]0xAE00, [char]0xD14C, [char]0xC2A4, [char]0xD2B8,
    [char]0x003A, [char]0x0020,
    [char]0xC0BC, [char]0xC131, [char]0xC804, [char]0xC790, [char]0x0020,
    [char]0xB9E4, [char]0xC218, [char]0x0020,
    [char]0xC131, [char]0xACF5, [char]0x0020,
    [char]0xD604, [char]0xC7AC, [char]0xAC00, [char]0x0020,
    [char]0x0037, [char]0x0032, [char]0x002C, [char]0x0033, [char]0x0030,
    [char]0x0030, [char]0xC6D0
)

if (Test-Path -LiteralPath $setupScript) {
    . $setupScript -Quiet
}

$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Value
    )
    $script:checks.Add([pscustomobject]@{Name = $Name; Ok = $Ok; Value = $Value}) | Out-Null
}

$codePageOutput = (& chcp) -join " "
Add-Check "PowerShellVersion" ($PSVersionTable.PSVersion.Major -ge 5) ($PSVersionTable.PSVersion.ToString())
Add-Check "PowerShellEdition" $true ([string]$PSVersionTable.PSEdition)
Add-Check "CodePage" ($codePageOutput -match "65001") $codePageOutput
Add-Check "ConsoleInputEncoding" ([Console]::InputEncoding.CodePage -eq 65001) ([Console]::InputEncoding.WebName)
Add-Check "ConsoleOutputEncoding" ([Console]::OutputEncoding.CodePage -eq 65001) ([Console]::OutputEncoding.WebName)
Add-Check "OutputEncoding" ($OutputEncoding.CodePage -eq 65001) ($OutputEncoding.WebName)
Add-Check "PYTHONUTF8" ($env:PYTHONUTF8 -eq "1") ([string]$env:PYTHONUTF8)
Add-Check "PYTHONIOENCODING" ($env:PYTHONIOENCODING -eq "utf-8") ([string]$env:PYTHONIOENCODING)

if (Test-Path -LiteralPath $venvPython) {
    $pythonScript = "import sys, locale; print(sys.executable); print(sys.stdout.encoding); print(sys.stderr.encoding); print(locale.getpreferredencoding(False)); print('ok')"
    $pythonOutput = & $venvPython -c $pythonScript 2>&1
    $stdoutEncoding = if ($pythonOutput.Count -ge 2) { [string]$pythonOutput[1] } else { "" }
    $stderrEncoding = if ($pythonOutput.Count -ge 3) { [string]$pythonOutput[2] } else { "" }
    $localeEncoding = if ($pythonOutput.Count -ge 4) { [string]$pythonOutput[3] } else { "" }
    Add-Check "VenvPython" ($pythonOutput.Count -ge 5) (($pythonOutput | ForEach-Object { $_.ToString() }) -join " | ")
    Add-Check "PythonStdoutEncoding" ($stdoutEncoding -match "utf-8") $stdoutEncoding
    Add-Check "PythonStderrEncoding" ($stderrEncoding -match "utf-8") $stderrEncoding
    Add-Check "PythonPreferredEncoding" ($localeEncoding -match "utf-8") $localeEncoding
}
else {
    Add-Check "VenvPython" $false ("missing: {0}" -f $venvPython)
}

$tempFile = Join-Path $env:TEMP "auto_trading_encoding_check.txt"
try {
    Set-Content -LiteralPath $tempFile -Encoding UTF8 -Value $testText
    $roundTrip = Get-Content -LiteralPath $tempFile -Encoding UTF8 -Raw
    Add-Check "Utf8FileRoundTrip" ($roundTrip.Trim() -eq $testText) $tempFile
}
catch {
    Add-Check "Utf8FileRoundTrip" $false $_.Exception.Message
}
finally {
    Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
}

Write-Host $testText
foreach ($check in $checks) {
    $status = if ($check.Ok) { "PASS" } else { "FAIL" }
    Write-Host ("{0} {1}: {2}" -f $status, $check.Name, $check.Value)
}

if (($checks | Where-Object { -not $_.Ok }).Count -gt 0) {
    Write-Host "FAIL encoding check"
    exit 1
}

Write-Host "PASS encoding check"
