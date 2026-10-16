# Safe entry point: the old environment is never used.
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('data-check', 'backtest', 'paper')]
    [string]$Mode,
    [string]$Config = 'experiments/rb-demo.toml',
    [switch]$Activate,
    [string]$Resume,
    [int]$Duration = 0,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $projectRoot '.venv-tqsdk'
$python = Join-Path $environmentPath 'Scripts\python.exe'
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
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Run tools/setup.ps1 first.'
    }
    Push-Location $projectRoot
    try {
        if ($Help -or -not $Mode) {
            & $python -I -X utf8 -B tools/run_entry.py --help
        }
        else {
            & $python -I -B tools/environment_probe.py --expected-environment $environmentPath
            if ($LASTEXITCODE -ne 0) { throw 'Environment identity check failed.' }
            $runArguments = @($Mode, '--config', $Config)
            if ($Activate) { $runArguments += '--activate' }
            if ($Resume) { $runArguments += @('--resume', $Resume) }
            if ($Duration -ne 0) { $runArguments += @('--duration', [string]$Duration) }
            & $python -I -X utf8 -B tools/run_entry.py @runArguments
        }
        $runExitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
if ($runExitCode -ne 0) { throw "Research command failed: $runExitCode" }
