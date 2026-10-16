import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class Window:
    def __init__(self):
        self.events = SimpleNamespace(closing=Event(), loaded=Event())
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


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


def test_close_waits_for_session_cleanup(tmp_path):
    host = importlib.import_module("qf.window_host")
    page = tmp_path / "index.html"
    page.write_text("<html>close</html>", encoding="utf-8")
    done = False
    window = Window()

    def start(**kwargs):
        nonlocal done
        assert window.events.closing.handlers[0]() is False
        assert not window.destroyed
        done = True
        assert window.events.closing.handlers[0]() is True

    view = SimpleNamespace(create_window=lambda *a, **kw: window, start=start)
    host.run_window(page, object(), lambda: done, webview_module=view)


def test_real_window_embeds_sdk_resources_and_calls_bridge_without_account():
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("window_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WINDOW_SMOKE=" in result.stdout


def test_native_chart_labels_are_chinese_without_exposing_business_bridge():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("native_labels_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_LABELS_SMOKE=" in result.stdout
