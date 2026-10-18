"""真实独立窗口验收；只使用临时目录、合成行情和内存凭证。"""

import json
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import tqsdk  # noqa: E402
import webview  # noqa: E402
from research_sdk import BASE, Api, sdk_for  # noqa: E402
from test_credentials import MemoryStore  # noqa: E402
from test_workbench import Session  # noqa: E402

from qf.research_runtime import execute_research  # noqa: E402
from qf.research_session import ResearchSession  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


def forbid_real_api(*args, **kwargs):
    raise AssertionError("离线验收不得连接账户")


tqsdk.TqApi = forbid_real_api


class UiApi(Api):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        values = [1000.0] * 34 + [999.0] * 5 + [1006.0, 1000.0]
        self.serial = pd.DataFrame(
            [
                dict(
                    id=i,
                    datetime=BASE + (i - (len(values) - 6)) * 60_000_000_000,
                    open=v,
                    high=v,
                    low=v,
                    close=v,
                    volume=10,
                    close_oi=20,
                )
                for i, v in enumerate(values)
            ]
        )
        self.live = "backtest" not in kwargs

    def wait_update(self, **kwargs):
        if self.live:
            time.sleep(0.03)
            self.steps += 1
            self.quote.datetime = (
                pd.Timestamp("2025-03-03 09:05:00") + pd.Timedelta(seconds=self.steps)
            ).strftime("%Y-%m-%d %H:%M:%S.%f")
            return True
        result = super().wait_update(**kwargs)
        index = self.serial.index[-1]
        price = self.quote.last_price
        self.serial.loc[index, "close"] = price
        self.serial.loc[index, "high"] = max(self.serial.loc[index, "high"], price)
        self.serial.loc[index, "low"] = min(self.serial.loc[index, "low"], price)
        return result

    def get_kline_serial(self, symbol, duration, **kwargs):
        self.subscriptions.append(("kline", duration))
        if duration != 60:
            count = len(self.serial)
            self.serial["datetime"] = [
                BASE + 300_000_000_000 - (count - 1 - i) * duration * 1_000_000_000
                for i in range(count)
            ]
        return self.serial


class MarketFixture(Session):
    def stop(self):
        self.running = False

    def set_workspace(self, symbols, panes):
        pass


class Harness:
    def __init__(self):
        self.window = None
        self.result = None
        self.confirmations = 0

    def create_window(self, *args, **kwargs):
        kwargs.update(width=960, height=680)
        window = webview.create_window(*args, **kwargs)
        self.window = window

        def confirmation(*a):
            self.confirmations += 1
            return True

        window.create_confirmation_dialog = confirmation
        window.events.loaded += lambda: self.install_probe(window)
        return window

    def install_probe(self, window):
        from System import Action

        script = Path(__file__).with_name("research_graph_probe.js").read_text("utf-8")
        tasks = []
        window.native.Invoke(
            Action(
                lambda: tasks.append(
                    window.native.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                        script
                    )
                )
            )
        )
        tasks[0].Wait(5000)

    def start(self, **kwargs):
        def exercise():
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if self.window.evaluate_js(
                        "!!window.pywebview?.api && "
                        "!!document.querySelector('[data-field=continuous]')?.options.length"
                    ):
                        break
                    time.sleep(0.1)
                self.window.evaluate_js(SCRIPT)
                deadline = time.monotonic() + 65
                while time.monotonic() < deadline:
                    value = self.window.evaluate_js("window.__researchSmoke||null")
                    if value and (value.get("done") or value.get("error")):
                        self.result = value
                        break
                    time.sleep(0.15)
                if not self.result:
                    self.result = dict(
                        error="流程超时",
                        state=self.window.evaluate_js(
                            "({stage:window.__researchStage,probe:window.__graphProbe,text:document.body.innerText.slice(-500)})"
                        ),
                    )
            except Exception as exc:
                self.result = dict(error=type(exc).__name__ + ": " + str(exc))
            finally:
                self.window.destroy()

        threading.Thread(target=exercise, daemon=True).start()
        webview.start(**kwargs)


PHASE = sys.argv[2] if len(sys.argv) > 2 else "write"
SCRIPT = Path(__file__).with_name(
    "research_reopen_browser.js" if PHASE == "reopen" else "research_workbench_browser.js"
).read_text("utf-8")


def main():
    location = nullcontext(sys.argv[1]) if len(sys.argv) > 1 else tempfile.TemporaryDirectory()
    with location as directory:
        root = Path(directory)
        store = MemoryStore()
        if PHASE == "write":
            store.save("fixture-user", "fixture-password")
        scenario = ["normal"]

        def execute(*args, **kwargs):
            sdk = sdk_for(scenario[0])
            sdk.TqApi = UiApi
            return execute_research(*args, sdk=sdk, **kwargs)

        session = ResearchSession(
            root / "results",
            execute_fn=execute,
            discover_fn=lambda **kw: [
                dict(
                    symbol="SHFE.rb2505",
                    name="螺纹钢2025年5月",
                    price_tick=1,
                    volume_multiple=10,
                    margin_per_lot=3000,
                    commission_per_lot=2,
                )
            ],
        )

        class FixtureBridge(WorkbenchBridge):
            def set_fixture_mode(self, value):
                assert value in ("normal", "partial", "reject", "disconnect")
                scenario[0] = value
                return {"ok": True}

        bridge = FixtureBridge(
            root, MarketFixture(), credential_store=store, research_session=session
        )
        harness = Harness()
        run_window(
            Path(__file__).resolve().parents[1] / "qf/web/index.html",
            bridge,
            bridge._request_close,
            webview_module=harness,
        )
        print("RESEARCH_WORKBENCH_RESULT=" + json.dumps(harness.result, ensure_ascii=False))
        if not harness.result or not harness.result.get("done") or harness.confirmations != 1:
            raise SystemExit(1)
        for database in (root / "results").glob("*/journal.sqlite3"):
            renamed = database.with_suffix(".closed")
            database.rename(renamed)
            renamed.rename(database)
        print("RESEARCH_WORKBENCH_OK")


if __name__ == "__main__":
    main()
