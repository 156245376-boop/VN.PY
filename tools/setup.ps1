# Lock-controlled installation into the isolated TqSdk environment.
[CmdletBinding()]
param(
    [switch]$InitializeLock,
    [switch]$UpdateLock,
    [switch]$RepairSdk,
    [string[]]$RepairPackage = @()
)

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
    if ($InitializeLock -and $UpdateLock) {
        throw 'Choose only one lock operation.'
    }
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
    elseif ($UpdateLock) {
        # Resolve explicit dependency changes while retaining compatible locked versions.
        & uv lock --project $projectRoot --python 3.13.11
        if ($LASTEXITCODE -ne 0) { throw "uv lock update failed: $LASTEXITCODE" }
    }
    $syncOptions = @('--project', $projectRoot, '--python', '3.13.11', '--locked',
                     '--extra', 'dev', '--extra', 'official-examples', '--extra', 'desktop')
    if ($RepairSdk) { $syncOptions += @('--reinstall-package', 'tqsdk') }
    foreach ($package in $RepairPackage) {
        if ($package -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
            throw "Invalid package name for repair: $package"
        }
        $syncOptions += @('--reinstall-package', $package)
    }
    & uv sync @syncOptions
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed: $LASTEXITCODE" }
    Write-Output 'TqSdk environment installation finished. Run tools/check.ps1 to verify.'
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
