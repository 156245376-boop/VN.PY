"""临时目录、内存凭证及真实 WebView2；严禁真实账户连接。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import research_workbench_smoke as base  # noqa: E402
from continuous_sdk import ContinuousSdkFixture  # noqa: E402
from test_credentials import MemoryStore  # noqa: E402

from qf.research_runtime import execute_research  # noqa: E402
from qf.research_session import ResearchSession  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


def main():
    root, phase = Path(sys.argv[1]), sys.argv[2]
    base.SCRIPT = Path(__file__).with_name('continuous_workbench_browser.js').read_text('utf-8')
    base.SCRIPT = 'window.__continuousPhase='+json.dumps(phase)+';\n'+base.SCRIPT
    store = MemoryStore()
    if phase == 'write':
        store.save('fixture-user', 'fixture-password')
    fixtures, faults = [], []

    def execute(*args, **kwargs):
        fixture = ContinuousSdkFixture(faults=faults)
        original = fixture.sdk.TqApi
        class Slow(original):
            def wait_update(self, **kw):
                time.sleep(.05)
                return super().wait_update(**kw)
        fixture.sdk.TqApi = Slow
        fixtures.append(fixture)
        return execute_research(*args, sdk=fixture.sdk, **kwargs)

    class Bridge(WorkbenchBridge):
        def set_fixture_mode(self, mode):
            assert mode in ('normal', 'mapping')
            faults[:] = [] if mode == 'normal' else ['mapping']
            return dict(ok=True)

    session = ResearchSession(root/'results', execute_fn=execute,
        discover_fn=lambda **kw: (_ for _ in ()).throw(AssertionError('无需单月份发现')))
    bridge = Bridge(root, base.MarketFixture(), credential_store=store, research_session=session)
    harness = base.Harness()
    run_window(Path(__file__).resolve().parents[1]/'qf/web/index.html', bridge,
               bridge._request_close, webview_module=harness)
    print('CONTINUOUS_WORKBENCH_RESULT='+json.dumps(harness.result, ensure_ascii=False))
    if not harness.result or not harness.result.get('done') or harness.confirmations != 1:
        raise SystemExit(1)
    assert (not fixtures) if phase == 'reopen' else len(fixtures) == 3
    assert not session.running
    print('CONTINUOUS_WORKBENCH_OK')


if __name__ == '__main__':
    main()
