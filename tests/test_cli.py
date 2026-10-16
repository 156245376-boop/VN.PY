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


def test_progress_stays_visible_while_sdk_output_and_credentials_are_suppressed(
        monkeypatch, capsys):
    import sys

    from qf import cli

    monkeypatch.setenv("TQ_USER", "private-user-for-test")
    monkeypatch.setenv("TQ_PASSWORD", "private-password-for-test")

    def run(mode, config, root, credentials, **kwargs):
        notify = kwargs["progress"]
        notify("sdk_loading")
        print("private-sdk-token-for-test")
        print("private-sdk-error-for-test", file=sys.stderr)
        notify("connecting")
        notify("observing", elapsed=0, duration=300)
        notify("heartbeat", elapsed=15, duration=300)
        notify("private-password-for-test")
        notify("stopping")
        return {"status": "stopped", "reason": "requested_stop"}

    monkeypatch.setattr(cli, "execute", run)
    assert cli.main(["paper", "--duration", "300"]) == 0
    output = capsys.readouterr()
    assert "正在加载" in output.out
    assert "正在连接" in output.out
    assert "观察" in output.out
    assert "15" in output.out and "300" in output.out
    assert "正在收尾" in output.out
    assert "private-" not in output.out + output.err
