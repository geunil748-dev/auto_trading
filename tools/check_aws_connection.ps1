$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"

function Read-DotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env 파일을 찾을 수 없습니다: $Path"
    }

    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $key, $value = $line.Split("=", 2)
        if ($key.StartsWith("AWS_") -and $value) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

Read-DotEnv -Path $envPath

function Resolve-AwsCli {
    $command = Get-Command aws -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $defaultPath = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }

    return $null
}

$aws = Resolve-AwsCli
if (-not $aws) {
    Write-Host "AWS CLI가 설치되어 있지 않습니다."
    Write-Host "설치 후 다시 실행하세요: https://aws.amazon.com/cli/"
    exit 2
}

if (-not $env:AWS_ACCESS_KEY_ID -or -not $env:AWS_SECRET_ACCESS_KEY) {
    Write-Host ".env에 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY를 입력해야 합니다."
    exit 3
}

if (-not $env:AWS_REGION) {
    $env:AWS_REGION = "ap-northeast-2"
}

& $aws sts get-caller-identity --region $env:AWS_REGION
