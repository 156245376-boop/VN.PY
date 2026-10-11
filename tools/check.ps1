# Deterministic verification entry point (R34.3).
# Keep this file ASCII so Windows PowerShell 5.1 can parse it without a BOM.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$ruff = Join-Path $root ".venv\Scripts\ruff.exe"
$mypy = Join-Path $root ".venv\Scripts\mypy.exe"
$lintImports = Join-Path $root ".venv\Scripts\lint-imports.exe"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    Invoke-Check "pytest (verified cases)" { & $python -m pytest -m "not pending_expected" }

    # R34.7 requires tests whose expected values await manual verification to FAIL.
    # A green run here would mean that protection is gone, so it is checked explicitly
    # rather than tolerated. Exit code 5 means no such case remains, which is the goal.
    Write-Host "`n=== pytest (R34.7: pending_expected must fail) ===" -ForegroundColor Cyan
    $pending = & $python -m pytest -m "pending_expected" --no-header -q 2>&1
    $pendingExit = $LASTEXITCODE
    Write-Host ($pending | Select-Object -Last 1)
    if ($pendingExit -eq 0) {
        throw "pending_expected cases passed; the R34.7 guard is broken"
    }
    if ($pendingExit -eq 5) {
        Write-Host "No unverified domain facts remain." -ForegroundColor Green
    }
    else {
        Write-Host "Unverified domain facts fail as required (R34.7)." -ForegroundColor Yellow
    }

    Invoke-Check "ruff" { & $ruff check src tests tools }
    Invoke-Check "mypy" { & $mypy src }
    Invoke-Check "import-linter" { & $lintImports }
    Invoke-Check "ac-coverage-markers" { & $python tools\requirements_coverage.py --summary }
    Write-Host "`nAll deterministic checks passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
