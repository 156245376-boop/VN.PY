import threading

import pytest

from qf.desktop import DesktopSession, allowed_chart_url


def test_window_session_uses_memory_credentials_and_masks_sdk_output(tmp_path, capsys):
    received = []

    def execute(mode, config, root, credentials, **kwargs):
        received.append((mode, credentials, kwargs["chart"], kwargs["hold_chart"]))
        print("private-sdk-response")
        kwargs["progress"]("chart_ready", url="http://127.0.0.1:12345")
        kwargs["progress"]("private-password")
        kwargs["progress"]("heartbeat", elapsed=15, duration=0, token="private-token")
        return {"status": "stopped", "reason": "requested_stop", "password": "private-password"}

    session = DesktopSession(tmp_path, execute_fn=execute)
    session.start("paper", "private-user", "private-password")
    session.thread.join(timeout=5)
    messages = list(session.drain())
    assert received == [("paper", ("private-user", "private-password"), True, False)]
    assert any(m.get("url") == "http://127.0.0.1:12345" for m in messages)
    assert "private-" not in str(messages) + str(capsys.readouterr())
    assert session.running is False


def test_stop_is_cooperative_and_concurrent_start_is_rejected(tmp_path):
    entered = threading.Event()

    def execute(mode, config, root, credentials, **kwargs):
        entered.set()
        while not kwargs["stop_requested"]():
            entered.wait(0.01)
        return {"status": "stopped", "reason": "requested_stop"}

    session = DesktopSession(tmp_path, execute_fn=execute)
    session.start("paper", "u", "p")
    assert entered.wait(2)
    with pytest.raises(ValueError):
        session.start("paper", "other", "other")
    session.stop()
    session.thread.join(timeout=5)
    assert not session.running
    assert list(session.drain())[-1]["type"] == "result"


def test_background_exception_and_remote_chart_url_never_escape(tmp_path):
    def execute(*args, **kwargs):
        kwargs["progress"]("chart_ready", url="https://example.com/private-token")
        raise RuntimeError("private-sdk-error")

    session = DesktopSession(tmp_path, execute_fn=execute)
    session.start("backtest", "u", "p")
    session.thread.join(timeout=5)
    messages = list(session.drain())
    assert messages[-1]["result"]["status"] == "failed"
    assert "private-" not in str(messages)
    assert not any("url" in m for m in messages)
    assert allowed_chart_url("http://127.0.0.1:12345")
    for url in ("http://0.0.0.0:12345", "http://127.0.0.1:12345/?token=secret",
                "http://127.0.0.1.evil.test:12345", "file:///tmp/a"):
        assert not allowed_chart_url(url)
