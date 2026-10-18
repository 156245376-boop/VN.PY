"""混合周期分屏的持续显示回归，只使用本机合成行情。"""

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
from test_credentials import MemoryStore  # noqa: E402
from test_market_session import FakeApi  # noqa: E402
from window_smoke import address, fixture_klines, ready, serve, stop  # noqa: E402

import qf.market_session as market_module  # noqa: E402
from qf.chart_workspace import ChartWorkspaceStore, default_workspace  # noqa: E402
from qf.indicator_catalog import default_item  # noqa: E402
from qf.indicator_store import IndicatorStore, default_indicators  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


def exercise():
    data = {'subscribed': [], 'klines': {}}
    for symbol in ['SHFE.rb2701', 'KQ.m@DCE.m']:
        for seconds in [60, 86400]:
            values = fixture_klines(symbol, seconds * 1_000_000_000, daily=seconds == 86400)
            data['klines'].setdefault(symbol, {}).update(values[symbol])
    server = threading.Thread(target=lambda: serve(data, probe=True), daemon=True)
    server.start()
    assert ready.wait(5)
    market_module.chart_address = lambda: address
    sdk = SimpleNamespace(TqApi=FakeApi, TqSim=lambda: 'local-sim', TqAuth=lambda u, p: None)
    errors, samples = [], []
    report = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with tempfile.TemporaryDirectory() as temp:
        config = default_workspace()
        config['layout'] = 'columns'
        config['panes'][0]['continuous'] = 'KQ.m@SHFE.rb'
        config['panes'][1].update(continuous='KQ.m@DCE.m', mode='continuous')
        ChartWorkspaceStore(Path(temp) / 'data/workbench').save(config)
        indicator_config = default_indicators()
        for index, pane in enumerate(indicator_config['panes'].values()):
            pane['items'] += [default_item(k) for k in ('ma', 'boll', 'macd', 'rsi', 'vp')]
            pane['items'][2]['params']['periods'] = [5+index, 20+index]
            pane['items'][4]['params']['short'] = 8+index
        IndicatorStore(Path(temp) / 'data/workbench').save(indicator_config)
        credentials = MemoryStore()
        credentials.save('offline-user', 'offline-pass')
        session = market_module.MarketSession(sdk=sdk)
        bridge = WorkbenchBridge(Path(temp), session, credential_store=credentials)
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs['hidden'] = not bool(report)
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def wait(js, timeout=15):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    if window.evaluate_js(js):
                        return
                    time.sleep(.1)
                raise AssertionError(js)

            def interact():
                try:
                    wait("typeof workspace!=='undefined'&&!!workspace&&nativeLabelsReady")
                    window.evaluate_js("""
                      window.stabilityRaw=[];window.indicatorObserved={};
                      addEventListener('message',e=>{const d=e.data;
                        if(d?.kind==='offline-native-probe'){
                          const f=[...document.querySelectorAll('.chart-pane iframe')]
                            .find(f=>f.contentWindow===e.source);
                          if(f)indicatorObserved[f.closest('[data-pane]').dataset.pane]
                            =d.indicatorPlots||[];}
                        if(d?.kind==='qf-chart-state')stabilityRaw.push({
                          id:d.pane_id,status:d.status,reason:d.reason,
                          width:d.viewport_width,height:d.viewport_height,
                          protocol:d.protocol});});
                      document.querySelector('#login-form').requestSubmit();
                    """)
                    wait("Object.keys(workspace.inspect().panes).length===2&&"
                         "Object.values(workspace.inspect().panes).every(p=>p.visible)")
                    wait("Object.values(indicatorObserved).filter(p=>p.length>=8).length===2")
                    for width, height, layout, expanded in [
                        (1280, 820, 'columns', True), (1800, 1050, 'columns', False),
                        (2540, 1320, 'columns', True), (2540, 1320, 'quad', True),
                        (2540, 1320, 'rows', True),
                    ]:
                        window.resize(width, height)
                        window.evaluate_js("""(()=>{
                          const layout=document.querySelector('#chart-layout');
                          if(layout.value!==LAYOUT){layout.value=LAYOUT;
                            layout.dispatchEvent(new Event('change'));}
                          const active=document.querySelector('#chart-workspace')
                            .classList.contains('workspace-expanded');
                          if(active!==EXPANDED)document.querySelector('#expand-workspace').click();
                        })()""".replace('LAYOUT', json.dumps(layout))
                             .replace('EXPANDED', json.dumps(expanded)))
                        before = window.evaluate_js("""(()=>{
                          const bar=document.querySelector('.account-split');
                          return bar&&!bar.hidden?bar.getBoundingClientRect().top:null;
                        })()""")
                        assert before is not None, '图表与账户之间缺少拖动分界'
                        # 上移边界应让出更多账户空间；普通/放大与双/四格均适用。
                        window.evaluate_js("""
                          for(let i=0;i<2;i++)document.querySelector('.account-split')
                            .dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp'}));
                        """)
                        after = window.evaluate_js(
                            "document.querySelector('.account-split').getBoundingClientRect().top")
                        assert after < before - 40, f'账户分界未上移：{before}/{after}'
                        window.evaluate_js("""
                          for(let i=0;i<2;i++)document.querySelector('.account-split')
                            .dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown'}));
                        """)
                        restored = window.evaluate_js(
                            "document.querySelector('.account-split').getBoundingClientRect().top")
                        assert abs(restored - before) < 2, (
                            f'来回调整产生偏移：{width}/{layout}/{expanded}/{before}/{restored}')
                        # 尺寸变化后允许收敛，然后完整采样持续状态，不能只等到一次 ready。
                        time.sleep(3)
                        wait("Object.keys(workspace.inspect().panes).every(id=>"
                             "indicatorObserved[id]?.length>=8)")
                        expected = {'pane-1': 'qf_ma_5', 'pane-2': 'qf_ma_6',
                                    'pane-3': 'qf_ma_7', 'pane-4': 'qf_ma_8'}
                        for pane in window.evaluate_js('Object.keys(workspace.inspect().panes)'):
                            assert window.evaluate_js(
                                f'indicatorObserved[{json.dumps(pane)}].includes('
                                f'{json.dumps(expected[pane])})'), f'参数串格：{pane}'
                        phase = []
                        for _ in range(60):
                            sample = window.evaluate_js("""(()=>{
                              const s=workspace.inspect();
                              const grid=document.querySelector('.chart-grid');
                              const scroll=document.querySelector('.chart-grid-scroll');
                              return {width:innerWidth,height:innerHeight,config:s.config,
                                grid:{width:grid.clientWidth,height:grid.clientHeight,
                                  scrollWidth:scroll.scrollWidth,scrollHeight:scroll.scrollHeight,
                                  clientWidth:scroll.clientWidth,clientHeight:scroll.clientHeight,
                                  gridWidth:grid.scrollWidth,gridHeight:grid.scrollHeight,
                                  rect:grid.getBoundingClientRect().toJSON(),
                                  scrollRect:scroll.getBoundingClientRect().toJSON()},
                                panes:Object.fromEntries(Object.entries(s.panes).map(([id,p])=>[
                                  id,{visible:p.visible,viewport:p.viewport,request:p.request,
                                    status:p.state?.status,reason:p.state?.reason,
                                    width:p.state?.viewport_width,height:p.state?.viewport_height,
                                    protocol:p.state?.protocol}]))};})()""")
                            samples.append(sample)
                            phase.append(sample)
                            time.sleep(.1)
                        geometry = {tuple((id, p['viewport']['width'], p['viewport']['height'])
                                    for id, p in s['panes'].items()) for s in phase}
                        assert len(geometry) == 1, f'分屏尺寸循环变化：{width}/{layout}/{geometry}'
                    failures = [s for s in samples if any(not p['visible']
                                for p in s['panes'].values())]
                    assert not failures, f'分屏反复加载：{len(failures)}/{len(samples)}'
                except Exception as exc:
                    errors.append(f'{type(exc).__name__}: {exc}')
                finally:
                    if report:
                        report.parent.mkdir(parents=True, exist_ok=True)
                        raw = window.evaluate_js('window.stabilityRaw||[]')
                        report.write_text(json.dumps({'samples': samples, 'raw': raw,
                            'errors': errors}, ensure_ascii=False), encoding='utf-8')
                    window.destroy()

            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            run_window(Path(__file__).resolve().parents[1] / 'qf/web/index.html', bridge,
                       bridge._request_close)
        finally:
            session.stop()
            if session.thread:
                session.thread.join(5)
            stop.set()
            server.join(5)
        assert not errors, errors
    print('WORKSPACE_STABILITY_OK')


if __name__ == '__main__':
    exercise()
