# Lint + type-check + test. Run before committing.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Host "Create .venv first (see README)." -ForegroundColor Red; exit 1 }

$env:PYTHONUTF8 = "1"

Write-Host "`n== ruff ==" -ForegroundColor Cyan
& $python -m ruff check app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n== pytest ==" -ForegroundColor Cyan
& $python -m pytest -q
exit $LASTEXITCODE
