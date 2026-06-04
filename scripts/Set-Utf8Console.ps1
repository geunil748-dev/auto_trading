param(
    [switch]$Quiet
)

$utf8NoBom = New-Object System.Text.UTF8Encoding $false

try {
    chcp 65001 | Out-Null
}
catch {
}

try {
    [Console]::InputEncoding = $utf8NoBom
}
catch {
}

try {
    [Console]::OutputEncoding = $utf8NoBom
}
catch {
}

$global:OutputEncoding = $utf8NoBom
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not $Quiet) {
    Write-Host ("CodePage=65001")
    Write-Host ("ConsoleInputEncoding={0}" -f [Console]::InputEncoding.WebName)
    Write-Host ("ConsoleOutputEncoding={0}" -f [Console]::OutputEncoding.WebName)
    Write-Host ("OutputEncoding={0}" -f $OutputEncoding.WebName)
    Write-Host ("PYTHONUTF8={0}" -f $env:PYTHONUTF8)
    Write-Host ("PYTHONIOENCODING={0}" -f $env:PYTHONIOENCODING)
}
