import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv-tqsdk/Scripts/python.exe"


def test_help_does_not_require_credentials_or_session():
    result = subprocess.run([str(PYTHON), "-I", "-X", "utf8", "-B", "tools/run_entry.py", "--help"],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert all(command in result.stdout for command in ("data-check", "backtest", "paper"))


def test_live_command_is_rejected_before_credentials():
    result = subprocess.run([str(PYTHON), "-I", "-X", "utf8", "-B", "tools/run_entry.py", "live"],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr
