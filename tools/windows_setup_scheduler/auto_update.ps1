param(
    [string]$Workspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Branch = "main",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

function Write-AutoUpdateLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $script:ResolvedLogPath -Encoding UTF8 -Value "[$timestamp]"
    Add-Content -LiteralPath $script:ResolvedLogPath -Encoding UTF8 -Value $Message
    Add-Content -LiteralPath $script:ResolvedLogPath -Encoding UTF8 -Value ""
}

function Invoke-Checked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )

    & $Exe @ArgumentList 2>&1 | ForEach-Object {
        Add-Content -LiteralPath $script:ResolvedLogPath -Encoding UTF8 -Value $_.ToString()
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Exe $($ArgumentList -join ' ')"
    }
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$logDir = Join-Path $workspacePath "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:ResolvedLogPath = if ($LogPath) { $LogPath } else { Join-Path $logDir "auto_update.log" }

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git was not found in PATH."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workspacePath ".git"))) {
        throw "Workspace is not a Git repository: $workspacePath"
    }

    $dirty = git -C $workspacePath status --porcelain --untracked-files=normal
    if ($dirty) {
        Write-AutoUpdateLog "Update failed`nError: Local changes detected. This server clone must stay read-only.`n$dirty"
        exit 1
    }

    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "fetch", "origin", $Branch)

    $local = (git -C $workspacePath rev-parse "HEAD").Trim()
    $remote = (git -C $workspacePath rev-parse "origin/$Branch").Trim()
    if ($local -eq $remote) {
        Write-AutoUpdateLog "No changes detected"
        exit 0
    }

    git -C $workspacePath merge-base --is-ancestor HEAD "origin/$Branch" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-AutoUpdateLog "Update failed`nError: origin/$Branch is not a fast-forward from local HEAD. Manual intervention required."
        exit 1
    }

    Write-AutoUpdateLog "Changes detected`nRunning git pull --ff-only"
    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "checkout", $Branch)
    Invoke-Checked -Exe "git" -ArgumentList @("-C", $workspacePath, "pull", "--ff-only", "origin", $Branch)

    Write-AutoUpdateLog "Running update_local_server.ps1"
    $updateScript = Join-Path $workspacePath "tools\windows_setup_scheduler\update_local_server.ps1"
    Invoke-Checked -Exe "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $updateScript,
        "-Workspace", $workspacePath,
        "-Branch", $Branch,
        "-SkipPull"
    )

    Write-AutoUpdateLog "Update completed successfully"
}
catch {
    Write-AutoUpdateLog "Update failed`nError: $($_.Exception.Message)"
    exit 1
}
