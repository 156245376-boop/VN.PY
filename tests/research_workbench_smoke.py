"""真实独立窗口验收；只使用临时目录、合成行情和内存凭证。"""

import json
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tqsdk  # noqa: E402
import webview  # noqa: E402
from pivot_sdk import PivotApi, sdk_for_pivot  # noqa: E402
from test_credentials import MemoryStore  # noqa: E402
from test_workbench import Session  # noqa: E402

from qf.research_runtime import execute_research  # noqa: E402
from qf.research_session import ResearchSession  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


def forbid_real_api(*args, **kwargs):
    raise AssertionError("离线验收不得连接账户")


tqsdk.TqApi = forbid_real_api


class UiApi(PivotApi):
    def wait_update(self, **kwargs):
        if not self.live:
            time.sleep(.6)
        return super().wait_update(**kwargs)


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
            if scenario[0] == 'expiry':
                kwargs['progress']('research_progress', details=dict(
                    stage='history', percent=None, completed_bars=0, fill_count=0,
                    elapsed_seconds=2.6, last_advance_age_seconds=2.6, current_ns=None))
                return dict(status='frozen', reason='contract_range_exceeds_expiry',
                            run_id='fixture-expiry-no-data')
            sdk = sdk_for_pivot(scenario[0])
            sdk.TqApi = UiApi
            return execute_research(*args, sdk=sdk, **kwargs)

        session = ResearchSession(
            root / "results",
            execute_fn=execute,
            discover_fn=lambda **kw: [
                dict(
                    symbol="SHFE.rb2505",
                    name="螺纹钢2025年5月",
                    expire_datetime=datetime(2025, 5, 15, 15,
                        tzinfo=timezone(timedelta(hours=8))).timestamp(),
                    price_tick=1,
                    volume_multiple=10,
                    margin_per_lot=3000,
                    commission_per_lot=2,
                )
            ],
        )

        class FixtureBridge(WorkbenchBridge):
            def set_fixture_mode(self, value):
                assert value in ("normal", "partial", "reject", "disconnect", "expiry")
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
        print("PIVOT_RESEARCH_OK")


if __name__ == "__main__":
    main()
