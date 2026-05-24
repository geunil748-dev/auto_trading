$workspace = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace "src"

& $python -m trading_bot run-scheduler --monitor-state "monitor/state.json"
