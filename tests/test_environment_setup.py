"""安装失败不能污染旧环境或覆盖已有锁文件。"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def run_setup(tmp_path: Path, *, existing_lock: bool, variables_present: bool) -> tuple[dict, Path]:
    source = ROOT / "tools/setup.ps1"
    assert source.is_file(), "environment setup script is not implemented"
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copyfile(source, project / "tools/setup.ps1")
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\n', encoding="utf-8")
    if existing_lock:
        (project / "uv.lock").write_bytes(b"existing-lock\n")
    present = "$true" if variables_present else "$false"
    script = r'''
$ErrorActionPreference = 'Stop'
$names = @('VIRTUAL_ENV','PYTHONPATH','PYTHONHOME','UV_PROJECT_ENVIRONMENT')
$before = @{}
foreach ($name in $names) {
    $value = if (VARIABLES_PRESENT) { 'old-' + $name } else { $null }
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    $before[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$global:calls = 0
$global:selected = $null
function global:uv {
    $global:calls++
    $global:selected = $env:UV_PROJECT_ENVIRONMENT
    $global:LASTEXITCODE = 23
}
$failed = $false
try { & 'SCRIPT_PATH' -InitializeLock } catch { $failed = $true }
$restored = $true
foreach ($name in $names) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process') -cne $before[$name]) {
        $restored = $false
    }
}
@{failed=$failed;calls=$global:calls;selected=$global:selected;restored=$restored} |
    ConvertTo-Json -Compress
'''.replace("VARIABLES_PRESENT", present).replace(
        "SCRIPT_PATH", str(project / "tools/setup.ps1").replace("'", "''")
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return json.loads(result.stdout), project


@pytest.mark.parametrize("variables_present", [True, False])
def test_setup_restores_environment_on_uv_failure(tmp_path, variables_present):
    result, project = run_setup(tmp_path, existing_lock=False, variables_present=variables_present)
    assert result["failed"] is True
    assert result["restored"] is True
    assert result["calls"] == 1
    assert Path(result["selected"]) == project / ".venv-tqsdk"
    assert not (project / ".venv").exists()
    assert not (project / ".venv-tqsdk").exists()
    assert not (project / "uv.lock").exists()


def test_initialize_lock_refuses_existing_lock(tmp_path):
    result, project = run_setup(tmp_path, existing_lock=True, variables_present=True)
    assert result["failed"] is True
    assert result["restored"] is True
    assert result["calls"] == 0
    assert (project / "uv.lock").read_bytes() == b"existing-lock\n"


@pytest.mark.parametrize("operation", ["-UpdateLock", "-RepairSdk"])
def test_explicit_maintenance_preserves_environment_and_installs_examples(tmp_path, operation):
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copyfile(ROOT / "tools/setup.ps1", project / "tools/setup.ps1")
    (project / "uv.lock").write_bytes(b"existing-lock\n")
    script = r'''
$ErrorActionPreference = 'Stop'
$env:UV_PROJECT_ENVIRONMENT = 'old-environment'
$global:calls = [Collections.Generic.List[object]]::new()
function global:uv {
    $global:calls.Add(@{args=@($args);selected=$env:UV_PROJECT_ENVIRONMENT})
    $global:LASTEXITCODE = 0
}
$succeeded = $true
try { & 'SCRIPT_PATH' OPERATION | Out-Null } catch { $succeeded = $false }
@{succeeded=$succeeded;calls=@($global:calls.ToArray());restored=$env:UV_PROJECT_ENVIRONMENT} |
    ConvertTo-Json -Depth 5 -Compress
'''.replace("SCRIPT_PATH", str(project / "tools/setup.ps1").replace("'", "''")).replace(
        "OPERATION", operation,
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    info = json.loads(result.stdout)
    assert info["succeeded"] is True
    assert info["restored"] == "old-environment"
    expected = [["sync", "--project", str(project), "--python", "3.13.11", "--locked",
                 "--extra", "dev", "--extra", "official-examples"]]
    if operation == "-UpdateLock":
        expected.insert(0, ["lock", "--project", str(project), "--python", "3.13.11"])
    else:
        expected[0] += ["--reinstall-package", "tqsdk"]
    assert [call["args"] for call in info["calls"]] == expected
    assert all(Path(call["selected"]) == project / ".venv-tqsdk" for call in info["calls"])
    assert (project / "uv.lock").read_bytes() == b"existing-lock\n"


def load_probe():
    assert (ROOT / "tools/environment_probe.py").is_file(), "environment probe is not implemented"
    return importlib.import_module("tools.environment_probe")


def test_environment_probe_rejects_wrong_prefix(tmp_path, monkeypatch):
    probe = load_probe()
    expected = Path(sys.prefix).resolve()
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    with pytest.raises(probe.EnvironmentCheckError):
        probe.verify_environment(expected)


def test_environment_probe_rejects_wrong_sdk_path(tmp_path, monkeypatch):
    probe = load_probe()
    import tqsdk

    monkeypatch.setattr(tqsdk, "__file__", str(tmp_path / "tqsdk/__init__.py"))
    with pytest.raises(probe.EnvironmentCheckError):
        probe.verify_environment(Path(sys.prefix))
