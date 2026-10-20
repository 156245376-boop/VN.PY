"""真实 SDK 页面“全屏/还原”右上角固定；使用内存数据，不连接账户。"""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402
from window_smoke import address, ready, serve, stop  # noqa: E402

from qf.research_chart_assets import NATIVE_TOOLBAR_CSS, chart_html  # noqa: E402
from qf.window_host import run_window  # noqa: E402

PROBE = Path(__file__).with_name("native_toolbar_browser.js").read_text(encoding="utf-8")
TOOLBAR = Path(__file__).parents[1] / "qf/web/native-toolbar.js"


def exercise():
    import tqsdk
    assets = Path(tqsdk.__file__).parent / "web"
    html = chart_html(assets)
    assert ".qf-native-top-actions" in html and ".qf-native-fullscreen" in html, "工具栏CSS未注入"
    assert 'src="/native-toolbar.js"' in html, "工具栏脚本未加载"

    toolbar_js = TOOLBAR.read_text(encoding="utf-8") if TOOLBAR.exists() else ""
    extra = ("(()=>{const s=document.createElement('style');s.textContent="
             + json.dumps(NATIVE_TOOLBAR_CSS)
             + ";document.head.appendChild(s);})();" + toolbar_js + PROBE)

    data = {"action": {"mode": "run", "accounts": {}, "user_name": "offline",
                       "file_name": "workbench_entry.py"},
            "subscribed": [{"symbol": "SHFE.rb2701", "dur_nano": 60000000000}]}
    server = threading.Thread(target=lambda: serve(data, probe=True, extra_script=extra),
                              daemon=True)
    server.start()
    assert ready.wait(5)
    result, errors = {}, []
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / "index.html"
        page.write_text(
            '<html><body style="margin:0"><iframe id="chart"'
            ' style="width:100%;height:560px;border:0"></iframe><script>'
            'window.probe=null;addEventListener("message",e=>{'
            'if(e.data?.kind==="native-toolbar-result")window.probe=e.data;});'
            'document.querySelector("#chart").src=ADDRESS;</script></body></html>'
            .replace("ADDRESS", json.dumps(address)), encoding="utf-8")
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs["hidden"] = True
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def interact():
                try:
                    end = time.monotonic() + 12
                    while time.monotonic() < end:
                        observed = window.evaluate_js("window.probe")
                        if observed:
                            result.update(observed)
                            break
                        time.sleep(0.05)
                    if "result" not in result and "error" not in result:
                        raise AssertionError("未收到工具栏探针结果")
                    if "error" in result:
                        raise AssertionError(result["error"])
                    assert result["result"]["pinned"] is True, result
                except Exception as exc:
                    errors.append(str(exc))
                finally:
                    window.destroy()

            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            run_window(page, object(), lambda: True)
        finally:
            stop.set()
            server.join(4)
    assert not server.is_alive()
    assert not errors, errors
    print("NATIVE_TOOLBAR_OK=" + json.dumps(result))


if __name__ == "__main__":
    exercise()
