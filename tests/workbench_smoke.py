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
from test_credentials import MemoryStore  # noqa: E402
from test_market_session import FakeApi  # noqa: E402
from window_smoke import address, fixture_klines, ready, serve, stop  # noqa: E402

import qf.market_session as market_module  # noqa: E402
from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402
from qf.workbench_store import WorkbenchStore  # noqa: E402


def exercise():
    native_data = {
        "action": {
            "mode": "run",
            "accounts": {},
            "user_name": "offline",
            "file_name": "workbench_entry.py",
        },
        "subscribed": [
            {"symbol": "DCE.m2701", "dur_nano": 60000000000},
            {"symbol": "SHFE.rb2701", "dur_nano": 60000000000},
            {"symbol": "KQ.m@DCE.m", "dur_nano": 86400000000000},
        ],
        "klines": {},
    }
    server = threading.Thread(target=lambda: serve(native_data, probe=True), daemon=True)
    server.start()
    assert ready.wait(5)
    market_module.chart_address = lambda: address
    sdk = SimpleNamespace(TqApi=FakeApi, TqSim=lambda: "local-sim", TqAuth=lambda u, p: (u, p))
    result, errors = {}, []
    with tempfile.TemporaryDirectory() as temp:
        WorkbenchStore(Path(temp) / "data/workbench").save(
            [
                {
                    "continuous": "KQ.m@SHFE.rb",
                    "name": "螺纹钢",
                    "product": "rb",
                    "exchange": "SHFE",
                },
                {"continuous": "KQ.m@DCE.m", "name": "豆粕", "product": "m", "exchange": "DCE"},
            ],
            [],
        )
        FakeApi.block = threading.Event()
        FakeApi.catalog_block = threading.Event()
        session = market_module.MarketSession(sdk=sdk)

        class DelayedFavorites(WorkbenchBridge):
            def __init__(self):
                credential_store = MemoryStore()
                credential_store.save("offline-user", "offline-pass")
                super().__init__(Path(temp), session, credential_store=credential_store)
                self._save_started = threading.Event()
                self._save_release = threading.Event()
                self._revision_offset = 0

            def get_state(self):
                result = super().get_state()
                result["chart_revision"] += self._revision_offset
                return result

            def set_favorites(self, symbols):
                self._save_started.set()
                assert self._save_release.wait(5)
                return super().set_favorites(symbols)

        bridge = DelayedFavorites()
        original = webview.create_window

        def create(*args, **kwargs):
            # 截图验收须让 WebView2 合成器绘制；普通自动测试仍在隐藏窗口运行。
            kwargs["hidden"] = len(sys.argv) <= 1
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def check(js):
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    if window.evaluate_js(js):
                        return
                    time.sleep(0.05)
                details = window.evaluate_js("workspace.inspect()")
                raise AssertionError(js + " " + json.dumps(details, ensure_ascii=False))

            def interact():
                try:
                    check('document.querySelector("#login").disabled===false')
                    assert window.evaluate_js('!!document.querySelector("#chart-layout")')
                    window.evaluate_js("window.pane1=()=>workspace.inspect().panes['pane-1']")
                    assert (
                        window.evaluate_js('document.querySelector("#user").value')
                        == "offline-user"
                    )
                    assert window.evaluate_js('document.querySelector("#password").value') == ""
                    assert (
                        window.evaluate_js('document.querySelector("#password").required') is False
                    )
                    window.evaluate_js('document.querySelector("#login-form").requestSubmit()')
                    window.evaluate_js("""window.chartObservation=null;window.chartObservations={};
                      addEventListener('message',event=>{
                        if(event.data?.kind==='offline-native-probe'){
                          window.chartObservation=event.data;
                          const f=[...document.querySelectorAll('.chart-pane iframe')]
                            .find(f=>f.contentWindow===event.source);
                          if(f)chartObservations[f.closest('[data-pane]').dataset.pane]=event.data;
                        }
                      });""")
                    time.sleep(0.8)  # 复现缓存目录先于连接/行情到达。
                    check('document.querySelector("#chart-loading").hidden===false')
                    assert "已等待" in window.evaluate_js(
                        'document.querySelector("#loading-time").textContent'
                    )
                    assert (
                        window.evaluate_js(
                            'document.querySelector("#chart-progress").hasAttribute("value")'
                        )
                        is False
                    )
                    FakeApi.block.set()
                    check(
                        'document.querySelector("#loading-stage").textContent.includes("读取品种目录")'
                    )
                    assert window.evaluate_js('document.querySelector("#chart-progress").max') == 2
                    assert (
                        window.evaluate_js('document.querySelector("#chart-progress").value') == 0
                    )
                    FakeApi.catalog_block.set()
                    check('document.querySelector("#chart").hidden===false')
                    check('window.chartObservation?.original?.startsWith("SHFE.rb2701")')
                    # DOM/工具栏出现不等于收到有效 K 线，空数据仍应保留加载提示。
                    time.sleep(0.4)
                    assert not window.evaluate_js('document.querySelector("#chart-loading").hidden')
                    for symbol in ("SHFE.rb2701", "DCE.m2701"):
                        for duration in (
                            60000000000,
                            300000000000,
                            900000000000,
                            1800000000000,
                            3600000000000,
                            86400000000000,
                        ):
                            value = fixture_klines(symbol, duration)
                            native_data["klines"].setdefault(symbol, {}).update(value[symbol])
                    native_data["klines"].update(
                        fixture_klines("KQ.m@DCE.m", 86400000000000, daily=True)
                    )
                    native_data["_fixture_revision"] = 1
                    check('document.querySelector("#chart-loading").hidden===true')
                    before_indicators = window.evaluate_js('document.querySelector("#chart").src')
                    window.evaluate_js("""
                      document.querySelector('#indicators').click();
                      const addIndicator=kind=>{
                        document.querySelector('.indicator-kind').value=kind;
                        [...document.querySelectorAll('.indicator-panel button')]
                          .find(b=>b.textContent==='添加指标').click();};
                      addIndicator('ma');addIndicator('macd');addIndicator('vp');
                    """)
                    check("chartObservations['pane-1']?.indicatorPlots?.some(k=>k.startsWith('qf_ma_'))")
                    check("chartObservations['pane-1']?.indicatorPlots?.some(k=>k.startsWith('qf_macd_'))")
                    # 仅切换离线模拟 socket 状态；缓存仍存在时断线也要撤下指标。
                    socket = "document.querySelector('#chart').contentWindow.postMessage"
                    window.evaluate_js(socket+"({kind:'offline-socket-state',connected:false},'*')")
                    check("chartObservations['pane-1']?.indicatorPlots?.length===0")
                    window.evaluate_js(socket+"({kind:'offline-socket-state',connected:true},'*')")
                    check("chartObservations['pane-1']?.indicatorPlots?.some(k=>k.startsWith('qf_ma_'))")
                    assert (window.evaluate_js('document.querySelector("#chart").src')
                            == before_indicators)
                    window.evaluate_js(
                        "document.querySelector('.indicator-panel-head button').click()")
                    check('document.querySelector("#status").dataset.light==="green"')
                    check(
                        'document.querySelector(".account-metrics").textContent.inclu'
                        'des("1,000,000")'
                    )
                    assert (
                        window.evaluate_js(
                            'document.body.innerText.split("本地模拟账户 · 行情窗口").length-1'
                        )
                        == 1
                    )
                    assert "正在连接" not in window.evaluate_js(
                        'document.querySelector("#notice").textContent'
                    )
                    check('document.querySelectorAll("#market-rows tr").length===2')
                    for width, height in ((1280, 820), (960, 680), (1440, 900)):
                        window.resize(width, height)
                        time.sleep(0.15)
                        bounds = window.evaluate_js("""(()=>{
                          const card=document.querySelector('.market-card').getBoundingClientRect();
                          const side=document.querySelector('.right-column')
                            .getBoundingClientRect();
                          const footer=document.querySelector('.market-card footer')
                            .getBoundingClientRect();
                          return {cardRight:card.right,sideLeft:side.left,sideTop:side.top,
                            cardBottom:card.bottom,footerRight:footer.right,width:innerWidth,
                            pageWidth:document.body.scrollWidth};})()""")
                        assert (
                            bounds["cardRight"] <= bounds["sideLeft"] + 1
                            or bounds["sideTop"] >= bounds["cardBottom"] - 1
                        ), bounds
                        assert bounds["footerRight"] <= bounds["cardRight"] + 1, bounds
                        assert bounds["pageWidth"] <= bounds["width"] + 1, bounds
                    assert window.evaluate_js('document.querySelector("#password").value') == ""
                    window.evaluate_js(
                        'document.querySelector("#search").value="豆粕";'
                        'document.querySelector("#search").dispatchEvent('
                        'new Event("input"))'
                    )
                    check('document.querySelectorAll("#market-rows tr").length===1')
                    window.evaluate_js('document.querySelector("#market-rows tr").click()')
                    check('document.querySelector("#chart-title").textContent.includes("豆粕")')
                    check('document.querySelector("#chart").hidden===false')
                    check('window.chartObservation?.original?.startsWith("DCE.m2701")')
                    window.evaluate_js(
                        'document.querySelector("#chart-source").value="continuous";'
                        'document.querySelector("#chart-source").dispatchEvent('
                        'new Event("change"))'
                    )
                    check('window.chartObservation?.original?.startsWith("KQ.m@DCE.m")')
                    check('window.chartObservation?.original?.includes("1D")')
                    check('pane1().state?.status==="ready"')
                    for year in range(2016, 2027):
                        value = str(year)
                        window.evaluate_js(
                            'document.querySelector("#history-year").value='
                            + json.dumps(value)
                            + ";document.querySelector("
                            '"#history-year").dispatchEvent(new Event("change"))'
                        )
                        check(
                            "pane1().state?.visible?.first?.startsWith("
                            + json.dumps(value)
                            + ")&&pane1().state?.visible?.last?.startsWith("
                            + json.dumps(value)
                            + ")"
                        )
                    window.evaluate_js('document.querySelector("#history-latest").click()')
                    check('pane1().state?.visible?.last?.startsWith("2026")')
                    assert "图中已加载" in window.evaluate_js(
                        'document.querySelector("#history-summary").textContent'
                    )
                    assert "1天" in window.evaluate_js("window.chartObservation.selected")
                    assert session.snapshot()["chart_mode"] == "continuous"
                    assert "跨主力合约" in window.evaluate_js(
                        'document.querySelector("#history-note").textContent'
                    )
                    window.evaluate_js(
                        'document.querySelector("#chart-source").value="actual";'
                        'document.querySelector("#chart-source").dispatchEvent('
                        'new Event("change"))'
                    )
                    check('window.chartObservation?.original?.startsWith("DCE.m2701")')
                    detail = window.evaluate_js(
                        'document.querySelector("#chart-detail").textContent'
                    )
                    assert "2027年1月合约" in detail and "KQ.m@" not in detail, detail
                    assert window.evaluate_js(
                        'document.querySelector("#market-rows td:nth-child(3)").textContent'
                    ).startswith("豆粕")
                    assert "元/吨" in window.evaluate_js(
                        'document.querySelector("#market-rows td:nth-child(4)").textContent'
                    )
                    assert "手" in window.evaluate_js(
                        'document.querySelector("#market-rows td:nth-child(6)").textContent'
                    )
                    # 同一帧旧请求迟到，不能把现图改成错误状态。
                    check('pane1().state?.status==="ready"')
                    window.evaluate_js(
                        'dispatchEvent(new MessageEvent("message",{'
                        'source:document.querySelector("#chart").contentWindow,'
                        "origin:new URL(pane1().url).origin,"
                        'data:{kind:"qf-chart-state",'
                        'pane_id:"pane-1",generation:state.generation,revision:state.'
                        'chart_revision-1,status:"unsupported"}}))'
                    )
                    assert window.evaluate_js("pane1().problem") == ""
                    address_before = window.evaluate_js('document.querySelector("#chart").src')
                    window.evaluate_js('document.querySelector("#expand-chart").click()')
                    check('document.querySelector("#chart-card").classList.contains("expanded")')
                    assert (
                        window.evaluate_js('document.querySelector("#chart").src') == address_before
                    )
                    window.evaluate_js('dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))')
                    check('!document.querySelector("#chart-card").classList.contains("expanded")')
                    bad = native_data["klines"]["DCE.m2701"]["60000000000"]["data"]
                    timestamp = bad["1"]["datetime"]
                    bad["1"]["datetime"] = bad["0"]["datetime"]
                    native_data["_fixture_revision"] = 2
                    check('pane1().state?.status==="invalid"')
                    assert "时间重复" in window.evaluate_js(
                        'document.querySelector("#history-summary").textContent'
                    )
                    assert window.evaluate_js(
                        'document.querySelector("#chart").style.visibility==="hidden"'
                    )
                    bad["1"]["datetime"] = timestamp
                    native_data["_fixture_revision"] = 3
                    check('pane1().state?.status==="ready"')
                    names = window.evaluate_js("""[
                        QfLabels.contractName('CZCE.WH701',[
                          {name:'强麦主连',exchange:'CZCE',product:'WH'}]),
                        QfLabels.contractName('SHFE.zz2701',[]),
                        QfLabels.translate('SHFE.rb2701 30m',state.catalog)]""")
                    assert names == [
                        "强麦 · 701合约（1月）",
                        "名称待确认（SHFE.zz2701）",
                        "螺纹钢 · 2027年1月合约 30分钟",
                    ]
                    window.evaluate_js(
                        'document.querySelector("#search").value="";'
                        'document.querySelector("#search").dispatchEvent('
                        'new Event("input"));'
                        'document.querySelectorAll("#market-rows button")'
                        ".forEach(button=>button.click())"
                    )
                    assert bridge._save_started.wait(3)
                    # 收藏保存未返回期间，真实页面仍会轮询旧的服务端状态。
                    time.sleep(0.8)
                    bridge._save_release.set()
                    check('document.querySelector("#favorite-count").textContent==="2"')
                    assert set(bridge.get_state()["favorites"]) == {"KQ.m@SHFE.rb", "KQ.m@DCE.m"}
                    assert window.evaluate_js('!!document.querySelector("#chart-favorite")')
                    check(
                        'document.querySelector("#chart-favorite").textContent.includes("取消自选")'
                    )
                    frame_before = window.evaluate_js('document.querySelector("#chart").src')
                    window.evaluate_js('document.querySelector("#chart-favorite").click()')
                    check('document.querySelector("#favorite-count").textContent==="1"')
                    assert bridge.get_state()["favorites"] == ["KQ.m@SHFE.rb"]
                    window.evaluate_js("""document.querySelector('[data-symbol="KQ.m@SHFE.rb"]')
                      .dispatchEvent(new MouseEvent('contextmenu',{
                        bubbles:true,cancelable:true,clientX:200,clientY:300}));""")
                    check('!document.querySelector("#market-context-menu").hidden')
                    assert "取消自选" in window.evaluate_js(
                        'document.querySelector("#market-context-menu").textContent'
                    )
                    window.evaluate_js(
                        'document.querySelector("#market-context-menu button").click()'
                    )
                    check('document.querySelector("#favorite-count").textContent==="0"')
                    assert window.evaluate_js("selected") == "KQ.m@DCE.m"
                    window.evaluate_js("""document.querySelector('[data-symbol="KQ.m@DCE.m"]')
                      .dispatchEvent(new MouseEvent('contextmenu',{
                        bubbles:true,cancelable:true,clientX:200,clientY:300}));
                      document.querySelector('#market-context-menu button').click();""")
                    check('document.querySelector("#favorite-count").textContent==="1"')
                    assert bridge.get_state()["favorites"] == ["KQ.m@DCE.m"]
                    assert (
                        window.evaluate_js('document.querySelector("#chart").src') == frame_before
                    )
                    window.evaluate_js(
                        "document.querySelector('#chart-layout').value='quad';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    check("Object.keys(workspace.inspect().panes).length===4")
                    check(
                        "Object.values(workspace.inspect().panes).every(p=>p.state?.s"
                        'tatus==="ready")'
                    )
                    before_first = window.evaluate_js('document.querySelector("#chart").src')
                    window.evaluate_js(
                        "document.querySelector('#period-pane-2').value='1h';"
                        "document.querySelector('#period-pane-2').dispatchEvent(new E"
                        "vent('change'))"
                    )
                    check('workspace.inspect().panes["pane-2"].state?.duration===3600000000000')
                    assert (
                        window.evaluate_js('document.querySelector("#chart").src') == before_first
                    )
                    assert len(FakeApi.instances) == 1
                    window.evaluate_js(
                        "for(let i=0;i<20;i++)document.querySelector('.split-column')"
                        ".dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight'"
                        ",bubbles:true}))"
                    )
                    gap = window.evaluate_js("""(()=>{
                      const bar=document.querySelector('.split-column').getBoundingClientRect();
                      const first=document.querySelector('[data-pane="pane-1"]')
                        .getBoundingClientRect();
                      return Math.abs((bar.left+bar.right)/2-first.right-6)})()""")
                    assert gap < 2, gap
                    check("chartObservations['pane-1']?.layout?.plotWidth>"
                          "document.querySelector('#chart').clientWidth-160")
                    window.evaluate_js(
                        "document.querySelector('#chart-layout').value='single';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    # 后续检查回到固定的 pane-1。
                    window.evaluate_js(
                        "document.querySelector('#chart-layout').value='quad';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    window.evaluate_js(
                        "document.querySelector('[data-pane=\"pane-1\"] .section-title'"
                        ").dispatchEvent(new PointerEvent('pointerdown',{bubbles:true"
                        "}));"
                        "document.querySelector('#chart-layout').value='single';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    if len(sys.argv) > 1:
                        from Microsoft.Web.WebView2.Core import (
                            CoreWebView2CapturePreviewImageFormat,
                        )
                        from System import Action
                        from System.IO import FileAccess, FileMode, FileStream

                        if len(sys.argv) > 2 and sys.argv[2] == 'quad':
                            window.resize(1800, 1100)
                            window.evaluate_js("""
                              document.querySelector('#chart-layout').value='quad';
                              const layout=document.querySelector('#chart-layout');
                              layout.dispatchEvent(new Event('change'));
                              for(let i=0;i<20;i++)document.querySelector('.split-column')
                                .dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft'}));
                              document.querySelector('.account-view summary').click();
                              document.querySelector('#expand-workspace').click();
                            """)
                            for _ in range(6):
                                time.sleep(.5)
                                check("Object.keys(workspace.inspect().panes).length===4&&"
                                  "Object.values(workspace.inspect().panes).every(p=>"
                                  "p.state?.status==='ready'&&p.visible&&"
                                  "Math.abs(p.state.viewport_width-p.viewport.width)<=2&&"
                                  "Math.abs(p.state.viewport_height-p.viewport.height)<=2)")

                        if len(sys.argv) > 2 and sys.argv[2] == "chart":
                            window.evaluate_js(
                                'document.querySelector("#chart-title")'
                                '.scrollIntoView({block:"start"})'
                            )
                            time.sleep(0.4)
                        stream = FileStream(
                            str(Path(sys.argv[1]).resolve()), FileMode.Create, FileAccess.Write
                        )
                        tasks = []
                        window.native.Invoke(
                            Action(
                                lambda: tasks.append(
                                    window.native.webview.CoreWebView2.CapturePreviewAsync(
                                        CoreWebView2CapturePreviewImageFormat.Png, stream
                                    )
                                )
                            )
                        )
                        assert tasks[0].Wait(5000)
                        stream.Dispose()
                        if len(sys.argv) > 2 and sys.argv[2] == 'quad':
                            window.evaluate_js("document.querySelector('#expand-workspace').click()")
                            matrix = []
                            for physical_width, physical_height, scale in (
                                    (1280, 820, 1), (1280, 820, 1.25),
                                    (1280, 820, 1.5), (960, 680, 1.5)):
                                metrics = {'width': round(physical_width / scale),
                                           'height': round(physical_height / scale),
                                           'deviceScaleFactor': scale, 'mobile': False}
                                metrics_tasks = []
                                window.native.Invoke(Action(lambda output=metrics_tasks,
                                    value=metrics: output.append(
                                    window.native.webview.CoreWebView2
                                    .CallDevToolsProtocolMethodAsync(
                                        'Emulation.setDeviceMetricsOverride', json.dumps(value)))))
                                assert metrics_tasks[0].Wait(5000)
                                time.sleep(.2)
                                check('document.body.scrollWidth<=innerWidth+1')
                                box = window.evaluate_js("""(()=>{
                                  const a=document.querySelector('.market-card')
                                    .getBoundingClientRect();
                                  const b=document.querySelector('.right-column')
                                    .getBoundingClientRect();
                                  return {right:a.right,bottom:a.bottom,left:b.left,top:b.top,
                                    width:innerWidth,height:innerHeight};})()""")
                                assert box['right'] <= box['left'] + 1 or \
                                    box['top'] >= box['bottom'] - 1, box
                                matrix.append({**metrics, **box})
                            clear_tasks = []
                            window.native.Invoke(Action(lambda: clear_tasks.append(
                                window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                                    'Emulation.clearDeviceMetricsOverride', '{}'))))
                            assert clear_tasks[0].Wait(5000)
                            Path(sys.argv[1]).with_suffix('.json').write_text(
                                json.dumps({'method': 'CDP emulation, not OS DPI change',
                                            'matrix': matrix}, ensure_ascii=False, indent=2),
                                encoding='utf-8')
                    window.resize(980, 720)
                    check("document.body.scrollWidth<=innerWidth")
                    FakeApi.missing = {"KQ.m@SHFE.rb", "KQ.m@DCE.m"}
                    check('document.querySelector("#data-summary").textContent.includes("0 / 2")')
                    assert (
                        window.evaluate_js('document.querySelector("#status").dataset.light')
                        == "green"
                    )
                    assert "暂无有效报价" in window.evaluate_js(
                        'document.querySelector("#market-rows").textContent'
                    )
                    FakeApi.missing = set()
                    session_api = FakeApi.instances[-1]
                    session_api._data["notify"]["lost"] = {"code": 2019112911, "conn_id": "md"}
                    check('document.querySelector("#status").dataset.light==="red"')
                    check(
                        'document.querySelector(".account-state").textContent.includes("连接中断")'
                    )
                    stamp = bridge.get_state()["account"]["observed_at"]
                    time.sleep(0.3)
                    assert bridge.get_state()["account"]["observed_at"] == stamp
                    session_api._data["notify"]["restored"] = {"code": 2019112902, "conn_id": "md"}
                    check('document.querySelector("#status").dataset.light==="green"')
                    window.evaluate_js(
                        "document.querySelector('#chart-layout').value='quad';"
                        "document.querySelector('#chart-layout').dispatchEvent(new Ev"
                        "ent('change'))"
                    )
                    check(
                        "Object.values(workspace.inspect().panes).every(p=>p.state?.s"
                        'tatus==="ready")'
                    )
                    generation = bridge.get_state()["generation"]
                    window.evaluate_js('document.querySelector("#disconnect").click()')
                    check('document.querySelector("#status").textContent==="已断开"')
                    window.evaluate_js('document.querySelector("#login-form").requestSubmit()')
                    check("state.generation>" + str(generation))
                    check(
                        "Object.keys(workspace.inspect().panes).length===4&&Object.va"
                        'lues(workspace.inspect().panes).every(p=>p.state?.status==="'
                        'ready")'
                    )
                    window.evaluate_js('document.querySelector("[data-view=news]").click()')
                    assert (
                        window.evaluate_js('document.querySelector("#news-panel").hidden') is False
                    )
                    window.evaluate_js('document.querySelector("#disconnect").click()')
                    check('document.querySelector("#status").textContent==="已断开"')
                    window.evaluate_js('document.querySelector("#forget-login").click()')
                    check('document.querySelector("#user").value===""')
                    assert bridge.get_login_state()["saved"] is False
                    assert (
                        window.evaluate_js('document.querySelector("#password").required') is True
                    )
                    result.update(
                        search=True,
                        selection=True,
                        favorites=True,
                        chart=True,
                        responsive=True,
                        disconnect=True,
                        remembered_login=True,
                    )
                except Exception as exc:
                    line = exc.__traceback__.tb_lineno
                    errors.append(f"{type(exc).__name__} at line {line}: {exc}")
                finally:
                    FakeApi.catalog_block.set()
                    window.evaluate_js("window.qfPrepareExit?.()")
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
