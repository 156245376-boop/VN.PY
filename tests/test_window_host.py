import importlib
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def is_set(self):
        return True


class Window:
    def __init__(self):
        self.events = SimpleNamespace(closing=Event(), loaded=Event())
        self.destroyed = False
        self.confirmed = True
        self.dialogs = []
        self.scripts = []
        self.closed = threading.Event()

    def destroy(self):
        self.destroyed = True
        self.closed.set()

    def create_confirmation_dialog(self, title, message):
        self.dialogs.append((title, message))
        return self.confirmed

    def evaluate_js(self, script):
        self.scripts.append(script)


def test_requires_webview2_without_ie_fallback(tmp_path):
    host = importlib.import_module("qf.window_host")
    engines = []
    page = tmp_path / "index.html"
    page.write_text("<html>本机窗口</html>", encoding="utf-8")

    def start(**kwargs):
        engines.append(kwargs["gui"])
        raise RuntimeError("private-backend-response")

    view = SimpleNamespace(create_window=lambda *a, **kw: Window(), start=start)
    with pytest.raises(host.WindowHostError, match="WebView2") as caught:
        host.run_window(page, object(), lambda: True, webview_module=view)
    assert engines == ["edgechromium"]
    assert "private-" not in str(caught.value)


def test_chart_rejects_external_address():
    host = importlib.import_module("qf.window_host")
    assert host.show_chart("http://127.0.0.1:12345") == "http://127.0.0.1:12345"
    for url in ("https://example.com", "http://0.0.0.0:12345", "file:///etc/passwd",
                "http://user:pass@127.0.0.1:12345", "http://127.0.0.1:12345/?token=secret"):
        with pytest.raises(ValueError):
            host.show_chart(url)


def test_cancel_exit_keeps_window_and_session_running(tmp_path):
    host = importlib.import_module("qf.window_host")
    page = tmp_path / "index.html"
    page.write_text("<html>close</html>", encoding="utf-8")
    window = Window()
    window.confirmed = False
    stopped = []

    def start(**kwargs):
        assert window.events.closing.handlers[0]() is False
        assert window.dialogs and not window.destroyed
        assert not stopped and not window.scripts

    view = SimpleNamespace(create_window=lambda *a, **kw: window, start=start)
    host.run_window(page, object(), lambda: stopped.append(True) or True, webview_module=view)


def test_close_confirms_once_and_waits_for_cleanup_without_blocking_ui(tmp_path):
    host = importlib.import_module("qf.window_host")
    page = tmp_path / "index.html"
    page.write_text("<html>close</html>", encoding="utf-8")
    done, requested = threading.Event(), threading.Event()
    window = Window()

    def start(**kwargs):
        assert window.events.closing.handlers[0]() is False
        assert requested.wait(2)
        assert len(window.dialogs) == 1
        assert not window.destroyed
        assert window.events.closing.handlers[0]() is False
        assert len(window.dialogs) == 1
        done.set()
        assert window.closed.wait(2)
        assert window.events.closing.handlers[0]() is True
        assert len(window.dialogs) == 1

    def request_close():
        requested.set()
        return done.is_set()

    view = SimpleNamespace(create_window=lambda *a, **kw: window, start=start)
    try:
        host.run_window(page, object(), request_close, webview_module=view)
    finally:
        done.set()


def test_real_window_embeds_sdk_resources_and_calls_bridge_without_account():
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("window_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WINDOW_SMOKE=" in result.stdout


def test_native_exit_dialog_cancels_then_confirms_and_closes_process():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("window_close_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WINDOW_CLOSE_SMOKE=cancelled_then_confirmed" in result.stdout


def test_native_chart_labels_are_chinese_without_exposing_business_bridge():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("native_labels_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_LABELS_SMOKE=" in result.stdout
