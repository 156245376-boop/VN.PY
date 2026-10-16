# Lock-controlled installation into the isolated TqSdk environment.
[CmdletBinding()]
param([switch]$InitializeLock)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $projectRoot '.venv-tqsdk'
$lockPath = Join-Path $projectRoot 'uv.lock'
$names = @('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'UV_PROJECT_ENVIRONMENT')
$saved = @{}
foreach ($name in $names) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    foreach ($name in @('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:UV_PROJECT_ENVIRONMENT = $environmentPath
    if ((Test-Path -LiteralPath $environmentPath) -and
        ((Get-Item -LiteralPath $environmentPath -Force).Attributes -band
            [IO.FileAttributes]::ReparsePoint)) {
        throw 'The project environment must not be a link.'
    }
    if ($InitializeLock) {
        if (Test-Path -LiteralPath $lockPath) {
            throw 'uv.lock already exists. Initializing over an existing lock is forbidden.'
        }
        & uv lock --project $projectRoot --python 3.13.11
        if ($LASTEXITCODE -ne 0) { throw "uv lock failed: $LASTEXITCODE" }
    }
    elseif (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw 'uv.lock is missing. Use -InitializeLock only for an approved initial lock.'
    }
    & uv sync --project $projectRoot --python 3.13.11 --locked --extra dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed: $LASTEXITCODE" }
    Write-Output 'TqSdk environment installation finished. Run tools/check.ps1 to verify.'
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
