$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $root "mobile\stock_monitor_app"
$buildDir = "C:\Users\admin\develop\stock_monitor_app_build"
$apiUrl = if ($args.Count -gt 0) { $args[0] } else { "http://10.0.2.2:4174/api/state" }
$envPath = Join-Path $root ".env"

function Read-DotEnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $line = Get-Content -LiteralPath $Path -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Key))\s*=" } |
        Select-Object -First 1
    if (-not $line) {
        return ""
    }

    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

$monitorBearerToken = Read-DotEnvValue -Path $envPath -Key "MONITOR_BEARER_TOKEN"

$defaultJavaHome = "C:\Users\admin\develop\jdk-17"
$defaultAndroidHome = "C:\Users\admin\develop\android-sdk"
if (-not $env:JAVA_HOME -and (Test-Path -LiteralPath $defaultJavaHome)) {
    $env:JAVA_HOME = $defaultJavaHome
}
if (-not $env:ANDROID_HOME -and (Test-Path -LiteralPath $defaultAndroidHome)) {
    $env:ANDROID_HOME = $defaultAndroidHome
}
if (-not $env:ANDROID_SDK_ROOT -and $env:ANDROID_HOME) {
    $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
}
$extraPath = @()
if ($env:JAVA_HOME) {
    $extraPath += (Join-Path $env:JAVA_HOME "bin")
}
if ($env:ANDROID_HOME) {
    $extraPath += (Join-Path $env:ANDROID_HOME "platform-tools")
    $extraPath += (Join-Path $env:ANDROID_HOME "cmdline-tools\latest\bin")
}
$env:Path = (($extraPath | Where-Object { Test-Path -LiteralPath $_ }) -join ";") + ";" + $env:Path

function Resolve-Flutter {
    $command = Get-Command flutter -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $defaultPath = "C:\Users\admin\develop\flutter\bin\flutter.bat"
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }

    return $null
}

$flutter = Resolve-Flutter
if (-not $flutter) {
    Write-Host "Flutter가 설치되어 있지 않거나 PATH에 없습니다."
    Write-Host "설치 후 다시 실행하세요: https://docs.flutter.dev/get-started/install/windows/mobile"
    exit 2
}

if (Test-Path -LiteralPath $buildDir) {
    Remove-Item -Recurse -Force -LiteralPath $buildDir
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $sourceDir "*") -Destination $buildDir

Push-Location $buildDir
try {
    if (-not (Test-Path -LiteralPath "android")) {
        & $flutter create --platforms=android --project-name stock_monitor_app .
    }

    $manifest = "android\app\src\main\AndroidManifest.xml"
    $manifestText = Get-Content -LiteralPath $manifest -Raw
    if ($manifestText -notmatch "android.permission.INTERNET") {
        $manifestText = $manifestText -replace "<manifest([^>]*)>", "<manifest`$1>`n    <uses-permission android:name=`"android.permission.INTERNET`" />"
        [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $manifest).Path, $manifestText, $utf8NoBom)
    }

    & $flutter pub get
    $buildArgs = @(
        "build",
        "apk",
        "--release",
        "--dart-define=MONITOR_API_URL=$apiUrl"
    )
    if ($monitorBearerToken) {
        $buildArgs += "--dart-define=MONITOR_BEARER_TOKEN=$monitorBearerToken"
    }

    & $flutter @buildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "APK 빌드 실패: Flutter 출력의 Android SDK/JDK 설정을 확인하세요."
    }

    $apk = Join-Path $buildDir "build\app\outputs\flutter-apk\app-release.apk"
    if (-not (Test-Path -LiteralPath $apk)) {
        throw "APK 파일을 찾을 수 없습니다: $apk"
    }

    $outDir = Join-Path $sourceDir "dist"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    Copy-Item -Force -LiteralPath $apk -Destination (Join-Path $outDir "stock-monitor-release.apk")

    Write-Host "APK 생성 완료:"
    Write-Host (Join-Path $outDir "stock-monitor-release.apk")
}
finally {
    Pop-Location
}
