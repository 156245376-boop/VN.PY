"""真实窗口配置写入与跨进程恢复；不建立行情或账户连接。"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

import webview  # noqa: E402
from test_credentials import MemoryStore  # noqa: E402

from qf.workbench import WorkbenchBridge  # noqa: E402
from qf.workbench_store import WorkbenchStore  # noqa: E402


class Session:
    running = False

    def snapshot(self):
        return {"status": "idle", "catalog": [], "rows": [], "connected": False}

    def start(self, *args):
        raise AssertionError("恢复布局不能自动登录")

    def stop(self):
        pass


def exercise(root, phase):
    if phase == "write":
        WorkbenchStore(root / "data/workbench").save(
            [{"continuous": "KQ.m@SHFE.rb", "name": "螺纹钢", "exchange": "SHFE", "product": "rb"}],
            [],
        )
    release, entered = threading.Event(), threading.Event()
    counters = {"active": 0, "max": 0, "calls": 0}

    class Bridge(WorkbenchBridge):
        def save_workspace(self, config):
            counters["active"] += 1
            counters["max"] = max(counters["max"], counters["active"])
            counters["calls"] += 1
            try:
                if counters["calls"] == 1:
                    entered.set()
                    assert release.wait(5)
                return super().save_workspace(config)
            finally:
                counters["active"] -= 1

    bridge = Bridge(root, Session(), credential_store=MemoryStore())
    original = webview.create_window
    errors = []

    def create(*args, **kwargs):
        kwargs["hidden"] = True
        window = original(*args, **kwargs)
        window.create_confirmation_dialog = lambda *args: True

        def check(js):
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                if window.evaluate_js(js):
                    return
                time.sleep(0.04)
            raise AssertionError(js)

        def interact():
            try:
                check('typeof workspace!=="undefined"&&!!workspace')
                if phase == "write":
                    window.evaluate_js(
                        "document.querySelector('#chart-layout').value='quad';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    assert entered.wait(2)
                    window.evaluate_js(
                        "document.querySelector('#period-pane-2').value='1h';"
                        "document.querySelector('#period-pane-2').dispatchEvent(new E"
                        "vent('change'));"
                        "document.querySelector('#chart-source-pane-2').value='continuous';"
                        "document.querySelector('#chart-source-pane-2').dispatchEvent"
                        "(new Event('change'))"
                    )
                    time.sleep(0.2)
                    assert counters["max"] == 1, counters
                    release.set()
                    window.evaluate_js("document.querySelector('.account-view summary').click();"
                                       "document.querySelector('#expand-workspace').click()")
                    check('workspace.getConfig().account_collapsed===true')
                    check(
                        'document.querySelector("#workspace-save-note").textContent.i'
                        'ncludes("已保存")'
                    )
                    restored = bridge.get_workspace()["workspace"]
                    assert restored["layout"] == "quad" and restored["active"] == "pane-2"
                    pane = next(p for p in restored["panes"] if p["id"] == "pane-2")
                    assert pane["period"] == "1h" and pane["mode"] == "continuous"
                else:
                    check('workspace.getConfig().layout==="quad"')
                    assert window.evaluate_js("workspace.getConfig().active") == "pane-2"
                    assert (
                        window.evaluate_js(
                            'workspace.getConfig().panes.find(p=>p.id==="pane-2").period'
                        )
                        == "1h"
                    )
                    assert not window.evaluate_js(
                        '[...document.querySelectorAll("iframe")].some(f=>f.getAttrib'
                        'ute("src")?.startsWith("http"))'
                    )
                    assert counters["calls"] == 0
            except Exception as exc:
                errors.append(str(exc))
            finally:
                release.set()
                window.destroy()

        window.events.loaded += lambda: threading.Thread(target=interact).start()
        return window

    webview.create_window = create
    from qf.window_host import run_window

    run_window(Path(__file__).parents[1] / "qf/web/index.html", bridge, bridge._request_close)
    assert not errors, errors
    print("WORKSPACE_LIFECYCLE_OK " + phase)


if __name__ == "__main__":
    exercise(Path(sys.argv[1]), sys.argv[2])
