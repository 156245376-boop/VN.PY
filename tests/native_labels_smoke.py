"""真实 SDK 页面标签及点击行为；使用内存数据，不连接账户。"""

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

from qf.window_host import run_window  # noqa: E402


def exercise():
    catalog = [{"continuous": "KQ.m@SHFE.rb", "name": "螺纹钢主连",
                "exchange": "SHFE", "product": "rb", "price_unit": "元/吨"},
               {"continuous": "KQ.m@DCE.m", "name": "豆粕主连",
                "exchange": "DCE", "product": "m", "price_unit": "元/吨"}]
    data = {"action": {"mode": "run", "accounts": {}, "user_name": "offline",
                       "file_name": "workbench_entry.py"},
            "subscribed": [{"symbol": "SHFE.rb2701", "dur_nano": 60000000000},
                           {"symbol": "DCE.m2701", "dur_nano": 60000000000}]}
    server = threading.Thread(target=lambda: serve(data, probe=True), daemon=True)
    server.start()
    assert ready.wait(5)
    result, errors = {}, []
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / "index.html"
        page.write_text('''<html><head><style>
          body{margin:0}iframe{width:100%;height:560px;border:0;display:block}
          </style></head><body><iframe id="chart"></iframe><script>
          const catalog=CATALOG, address=ADDRESS;
          let observation=null;
          addEventListener('message',event=>{
            if(event.data?.kind==='qf-chart-ready')
              document.querySelector('#chart').contentWindow.postMessage(
                {kind:'qf-chart-labels',catalog},new URL(address).origin);
            if(event.data?.kind==='offline-native-probe')observation=event.data;
          });
          addEventListener('qf-native-labels-ready',()=>{
            document.querySelector('#chart').src=address;
          });
          // 未实现适配时仍加载原生页面，确保测试失败在原始英文标签上。
          setTimeout(()=>{if(!document.querySelector('#chart').getAttribute('src'))
            document.querySelector('#chart').src=address},1800);
          </script></body></html>'''.replace("CATALOG", json.dumps(catalog))
                        .replace("ADDRESS", json.dumps(address)), encoding="utf-8")
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs["hidden"] = True
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def interact():
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        observed = window.evaluate_js('observation')
                        if observed and "螺纹钢" in observed["text"]:
                            break
                        time.sleep(0.1)
                    assert observed and "主力行情 · 只读观察" in observed["text"], observed
                    assert "螺纹钢 · 2027年1月合约" in observed["text"], observed
                    assert "1分钟" in observed["text"], observed
                    assert "价格：元/吨" in observed["text"], observed
                    assert "图表服务" in observed["text"], observed
                    assert "图表行情" in observed["text"], observed
                    assert "workbench_entry.py" not in observed["text"], observed
                    assert observed["bridge"] is False, observed
                    assert observed["selected"].startswith("螺纹钢"), observed
                    assert observed["original"].startswith("SHFE.rb2701"), observed
                    layout = observed["layout"]
                    assert all(bottom <= layout["chartTop"] + 1
                               for bottom in layout["bottoms"]), layout
                    window.evaluate_js('document.querySelector("#chart").contentWindow'
                                       '.postMessage({kind:"offline-native-click"},"*")')
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        observed = window.evaluate_js('observation')
                        if observed["selected"].startswith("豆粕"):
                            break
                        time.sleep(0.1)
                    assert observed["selected"].startswith("豆粕 · 2027年1月合约"), observed
                    assert observed["original"].startswith("DCE.m2701"), observed
                    window.evaluate_js('document.querySelector("#chart").contentWindow'
                                       '.postMessage({kind:"offline-native-period"},"*")')
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        observed = window.evaluate_js('observation')
                        if "30m" in observed["original"]:
                            break
                        time.sleep(0.1)
                    assert "30m" in observed["original"], observed
                    assert "30分钟" in observed["selected"], observed
                    window.resize(980, 720)
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        observed = window.evaluate_js('observation')
                        if observed["layout"]["width"] <= 980:
                            break
                        time.sleep(0.1)
                    layout = observed["layout"]
                    assert all(bottom <= layout["chartTop"] + 1
                               for bottom in layout["bottoms"]), layout
                    result.update(chinese=True, no_bridge=True, clicked=True, period=True)
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
    print("NATIVE_LABELS_SMOKE=" + json.dumps(result))


if __name__ == "__main__":
    exercise()
