# Read-only archive, environment and dependency verification. No API sessions.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $projectRoot '.venv-tqsdk'
$python = Join-Path $environmentPath 'Scripts\python.exe'
$names = @('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'UV_PROJECT_ENVIRONMENT')
$saved = @{}
foreach ($name in $names) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Invoke-Check {
    param([string]$Name, [scriptblock]$Command)
    Write-Host "Checking $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed: $LASTEXITCODE" }
}

try {
    foreach ($name in @('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:UV_PROJECT_ENVIRONMENT = $environmentPath
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'TqSdk Python is missing. Run tools/setup.ps1.'
    }
    Push-Location $projectRoot
    try {
        Invoke-Check 'archive integrity' {
            & $python -I -B tools/verify_archive.py `
                --archive archive/legacy-vnpy-2026-10-15.zip `
                --sha256-file archive/legacy-vnpy-2026-10-15.sha256
        }
        Invoke-Check 'environment identity (no account session)' {
            & $python -I -B tools/environment_probe.py --expected-environment $environmentPath
        }
        Invoke-Check 'lock consistency' {
            & uv lock --project $projectRoot --python 3.13.11 --check --no-python-downloads
        }
        Invoke-Check 'installed versions' {
            & uv sync --project $projectRoot --python 3.13.11 `
                --locked --check --extra dev --extra official-examples --extra desktop `
                --no-python-downloads
        }
        Invoke-Check 'dependency compatibility' {
            & uv pip check --python $python --no-python-downloads
        }
        Invoke-Check 'official components and resources (no account session)' {
            & $python -I -B tools/native_inventory.py
        }
        Invoke-Check 'pytest' { & $python -I -B -m pytest }
        Invoke-Check 'ruff' { & $python -I -B -m ruff check qf tools tests }
        Write-Host 'All checks passed. No account session was created.'
    }
    finally { Pop-Location }
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
