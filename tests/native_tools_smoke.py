"""真实 SDK/WebView2 价格轴、尺寸及鼠标模式的离线集成验收。"""

import base64
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402
from window_smoke import address, fixture_klines, ready, serve, stop  # noqa: E402

from qf.window_host import run_window  # noqa: E402

PROBE = Path(__file__).with_name("native_tools_browser.js").read_text(encoding="utf-8")


def exercise():
    data = {"subscribed": [{"symbol": "SHFE.rb2701", "dur_nano": 60000000000}],
            "klines": fixture_klines("SHFE.rb2701", 60000000000)}
    preview = "--preview" in sys.argv
    script = PROBE.replace("PREVIEW", "true" if preview else "false")
    server = threading.Thread(target=lambda: serve(data, probe=True, extra_script=script),
                              daemon=True)
    server.start()
    assert ready.wait(5)
    result = {}
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / "index.html"
        page.write_text('''<html><body style="margin:0"><iframe id="chart"
          style="width:100%;height:650px;border:0"></iframe><script>
          window.probe=null;addEventListener('message',e=>{
            if(e.data?.kind==='native-tools-result')window.probe=e.data;
          });addEventListener('qf-native-labels-ready',()=>{
            document.querySelector('#chart').src=ADDRESS;
          });</script></body></html>'''.replace("ADDRESS", json.dumps(address)), encoding="utf-8")
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs["hidden"] = not preview
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def interact():
                try:
                    end = time.monotonic() + 16
                    while time.monotonic() < end:
                        observed = window.evaluate_js("window.probe")
                        if observed:
                            result.update(observed)
                            if preview and "result" in result:
                                from System import Action
                                tasks = []
                                window.native.Invoke(Action(lambda tasks=tasks: tasks.append(
                                    window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                                        "Page.captureScreenshot", '{"format":"png"}'))))
                                assert tasks[0].Wait(5000)
                                image = json.loads(str(tasks[0].Result))["data"]
                                target = (Path(__file__).resolve().parents[1]
                                          / ".superpowers/chart-tools-preview.png")
                                target.parent.mkdir(exist_ok=True)
                                target.write_bytes(base64.b64decode(image))
                            break
                        time.sleep(0.05)
                finally:
                    window.destroy()

            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            run_window(page, object(), lambda: True)
        finally:
            stop.set()
            server.join(5)
    assert "result" in result and "error" not in result, result
    assert result["result"]["bridge"] is False, result
    print("NATIVE_TOOLS_SMOKE=" + json.dumps(result))


if __name__ == "__main__":
    exercise()
