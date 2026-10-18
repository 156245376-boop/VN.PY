import subprocess
import sys
from pathlib import Path


def test_full_research_flow_in_real_webview(tmp_path):
    run_phase(tmp_path, "write")
    run_phase(tmp_path, "reopen")


def run_phase(root, phase):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            str(Path(__file__).with_name("research_workbench_smoke.py")),
            str(root),
            phase,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=100,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESEARCH_WORKBENCH_OK" in result.stdout
