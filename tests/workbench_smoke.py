"""真实桌面与真实行情会话控制流，数据由离线 SDK 替身提供。"""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402
from test_market_session import FakeApi  # noqa: E402
from window_smoke import address, ready, serve, stop  # noqa: E402

import qf.market_session as market_module  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


def exercise():
    server = threading.Thread(target=serve, daemon=True)
    server.start()
    assert ready.wait(5)
    market_module.chart_address = lambda: address
    sdk = SimpleNamespace(TqApi=FakeApi, TqSim=lambda: "local-sim", TqAuth=lambda u, p: (u, p))
    result, errors = {}, []
    with tempfile.TemporaryDirectory() as temp:
        session = market_module.MarketSession(sdk=sdk)
        bridge = WorkbenchBridge(Path(temp), session)
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs["hidden"] = True
            window = original(*args, **kwargs)

            def check(js):
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    if window.evaluate_js(js):
                        return
                    time.sleep(0.05)
                raise AssertionError(js)

            def interact():
                try:
                    check('document.querySelector("#login").disabled===false')
                    window.evaluate_js('document.querySelector("#user").value="offline-user";'
                                       'document.querySelector("#password").value="offline-pass";'
                                       'document.querySelector("#login-form").requestSubmit()')
                    check('document.querySelectorAll("#market-rows tr").length===2')
                    assert window.evaluate_js('document.querySelector("#password").value') == ""
                    window.evaluate_js('document.querySelector("#search").value="豆粕";'
                                       'document.querySelector("#search").dispatchEvent('
                                       'new Event("input"))')
                    check('document.querySelectorAll("#market-rows tr").length===1')
                    window.evaluate_js('document.querySelector("#market-rows tr").click()')
                    check('document.querySelector("#chart-title").textContent.includes("豆粕")')
                    check('document.querySelector("#chart").hidden===false')
                    window.evaluate_js('document.querySelector("#market-rows button").click()')
                    check('document.querySelector("#favorite-count").textContent==="1"')
                    if len(sys.argv) > 1:
                        from Microsoft.Web.WebView2.Core import (
                            CoreWebView2CapturePreviewImageFormat,
                        )
                        from System import Action
                        from System.IO import FileAccess, FileMode, FileStream
                        stream = FileStream(str(Path(sys.argv[1]).resolve()), FileMode.Create,
                                            FileAccess.Write)
                        tasks = []
                        window.native.Invoke(Action(lambda: tasks.append(
                            window.native.webview.CoreWebView2.CapturePreviewAsync(
                                CoreWebView2CapturePreviewImageFormat.Png, stream))))
                        assert tasks[0].Wait(5000)
                        stream.Dispose()
                    window.resize(980, 720)
                    check('document.body.scrollWidth<=innerWidth')
                    window.evaluate_js('document.querySelector("[data-view=news]").click()')
                    assert window.evaluate_js(
                        'document.querySelector("#news-panel").hidden') is False
                    window.evaluate_js('document.querySelector("#disconnect").click()')
                    check('document.querySelector("#status").textContent==="已断开"')
                    result.update(search=True, selection=True, favorites=True,
                                  chart=True, responsive=True, disconnect=True)
                except Exception as exc:
                    errors.append(str(exc))
                finally:
                    bridge.disconnect()
                    window.destroy()

            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            root = Path(__file__).resolve().parents[1]
            run_window(root / "qf/web/index.html", bridge, bridge._request_close)
        finally:
            session.stop()
            if session.thread:
                session.thread.join(4)
            stop.set()
            server.join(4)
        assert not errors, errors
        assert not session.running and not server.is_alive()
        cached = (Path(temp) / "data/workbench/settings.json").read_text(encoding="utf-8")
        assert "offline-pass" not in cached
    print("WORKBENCH_SMOKE=" + json.dumps(result))


if __name__ == "__main__":
    exercise()
