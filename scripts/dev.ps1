# Start SkillMirror locally.
#
#   .\scripts\dev.ps1              # http://127.0.0.1:8000
#   .\scripts\dev.ps1 -Port 8020   # another port
#   .\scripts\dev.ps1 -Reload      # auto-restart on code changes (kills in-flight jobs)

param(
    [int]$Port = 8000,
    [string]$HostAddr = "127.0.0.1",
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No virtualenv found. Create it first:" -ForegroundColor Yellow
    Write-Host "  py -3.13 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -e ."
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "No .env found - copy .env.example to .env and add OPENROUTER_API_KEY." -ForegroundColor Yellow
    Write-Host "Continuing in degraded (keyword-only) mode." -ForegroundColor Yellow
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$arguments = @("-m", "uvicorn", "app.main:app", "--host", $HostAddr, "--port", $Port)
if ($Reload) { $arguments += "--reload" }

Write-Host "SkillMirror -> http://${HostAddr}:$Port" -ForegroundColor Cyan
& $python @arguments
