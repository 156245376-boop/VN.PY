"""在独立进程验证真实 WebView2 和 SDK 静态图形服务，不建立账户会话。"""

import asyncio
import contextlib
import json
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tqsdk  # noqa: E402
import webview  # noqa: E402
from tqsdk.tqwebhelper import TqWebHelper  # noqa: E402

from qf.runtime import chart_address  # noqa: E402
from qf.window_host import run_window  # noqa: E402

ready, stop = threading.Event(), threading.Event()
address = chart_address()


def serve():
    async def main():
        helper = object.__new__(TqWebHelper)
        helper._api = SimpleNamespace(
            _auth=SimpleNamespace(_access_token="offline-fixture"), _ins_url="", _md_url="",
            _print=lambda *a, **k: ready.set(), _logger=logging.getLogger("offline"),
        )
        helper._data = {"action": {"mode": "run", "accounts": {}, "user_name": "offline"},
                        "trade": {}, "subscribed": [], "draw_chart_datas": {}, "snapshots": {}}
        helper._conn_diff_chans = set()
        helper._http_server_host = "127.0.0.1"
        helper._http_server_port = int(address.rsplit(":", 1)[1])
        helper._web_dir = str(Path(tqsdk.__file__).parent / "web")
        task = asyncio.create_task(helper.link_httpserver())
        try:
            while not stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            for channel in tuple(helper._conn_diff_chans):
                await channel.close()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(main())


class Bridge:
    def ping(self):
        return "bridge-ok"


def host_smoke():
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(5)
    result = {}
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / "index.html"
        page.write_text(
            '<html><body><div id="result"></div>'
            + f'<iframe id="chart" src="{address}" onload="this.dataset.loaded=1"></iframe>'
            + '<script>addEventListener("pywebviewready",async()=>{'
            + 'document.querySelector("#result").textContent=await pywebview.api.ping()})'
            + "</script></body></html>", encoding="utf-8",
        )
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs["hidden"] = True
            window = original(*args, **kwargs)

            def exercise():
                try:
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        value = window.evaluate_js(
                            '({text:document.querySelector("#result").textContent,'
                            'loaded:document.querySelector("#chart").dataset.loaded})')
                        if value.get("text") == "bridge-ok" and value.get("loaded") == "1":
                            result.update(value)
                            break
                        time.sleep(0.05)
                finally:
                    window.destroy()

            window.events.loaded += lambda: threading.Thread(target=exercise).start()
            return window

        webview.create_window = create
        try:
            run_window(page, Bridge(), lambda: True)
        finally:
            stop.set()
            thread.join(5)
    assert result == {"text": "bridge-ok", "loaded": "1"}, result
    assert not thread.is_alive()
    print("WINDOW_SMOKE=" + json.dumps(result))


if __name__ == "__main__":
    host_smoke()
