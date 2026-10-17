"""自建窗口的原生退出弹窗验收；只操作本测试进程的弹窗。"""

import ctypes
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webview  # noqa: E402

from qf.window_host import run_window  # noqa: E402


def answer_dialog(button_id):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetDlgItem.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    end = time.monotonic() + 5
    while time.monotonic() < end:
        matches = []

        def visit(hwnd, _, found=matches):
            pid, title = wintypes.DWORD(), ctypes.create_unicode_buffer(128)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                user32.GetWindowTextW(hwnd, title, len(title))
                if title.value == "确认退出":
                    found.append(hwnd)
            return True

        user32.EnumWindows(callback_type(visit), 0)
        if matches:
            button = user32.GetDlgItem(matches[0], button_id)
            assert button
            user32.SendMessageW(button, 0x00F5, 0, 0)  # BM_CLICK，仅限本进程确认框。
            return
        time.sleep(0.03)
    raise AssertionError("未出现原生确认退出弹窗")


def exercise():
    requested, cleanup_done = threading.Event(), threading.Event()
    original = webview.create_window
    errors = []

    def request_close():
        requested.set()
        return cleanup_done.is_set()

    def create(*args, **kwargs):
        kwargs["hidden"] = True
        window = original(*args, **kwargs)

        def interact():
            from System import Action

            try:
                window.native.BeginInvoke(Action(window.native.Close))
                answer_dialog(2)  # 取消。
                assert not requested.is_set()
                assert window.evaluate_js("window.prepared") is False
                window.native.BeginInvoke(Action(window.native.Close))
                answer_dialog(1)  # 确定。
                assert requested.wait(3)
                assert window.evaluate_js("window.prepared") is True
                assert not window.events.closed.is_set()
                cleanup_done.set()
                assert window.events.closed.wait(5)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                cleanup_done.set()
                window.create_confirmation_dialog = lambda *args: True
                window.destroy()

        window.events.loaded += lambda: threading.Thread(target=interact).start()
        return window

    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / "index.html"
        page.write_text("<html><body>退出测试<script>window.prepared=false;"
                        "window.qfPrepareExit=()=>{window.prepared=true};</script></body></html>",
                        encoding="utf-8")
        webview.create_window = create
        run_window(page, object(), request_close)
    assert not errors, errors
    print("WINDOW_CLOSE_SMOKE=cancelled_then_confirmed")


if __name__ == "__main__":
    exercise()
