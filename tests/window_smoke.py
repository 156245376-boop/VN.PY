"""在独立进程验证真实 WebView2 和 SDK 静态图形服务，不建立账户会话。"""

import asyncio
import contextlib
import json
import logging
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
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


def fixture_klines(symbol, duration, *, daily=False):
    """有完整中间年份的图形假数据，不连接任何账户。"""
    start = datetime(2016 if daily else 2026, 1, 5, tzinfo=timezone(timedelta(hours=8)))
    days = [start + timedelta(days=i) for i in range(3900)] if daily else []
    stamps = ([int(t.timestamp() * 1e9) for t in days if t.weekday() < 5] if daily else
              [int(start.timestamp() * 1e9) + i * duration for i in range(220)])
    return {symbol: {str(duration): {"last_id": len(stamps) - 1, "data": {
        str(i): {"datetime": value, "open": 3300, "high": 3310, "low": 3290,
                 "close": 3305, "volume": 10, "open_oi": 20, "close_oi": 20}
        for i, value in enumerate(stamps)}}}}


def serve(initial_data=None, *, probe=False, extra_script=""):
    async def main():
        helper = object.__new__(TqWebHelper)
        helper._api = SimpleNamespace(
            _auth=SimpleNamespace(_access_token="offline-fixture"), _ins_url="", _md_url="",
            _print=lambda *a, **k: ready.set(), _logger=logging.getLogger("offline"),
        )
        helper._data = {"action": {"mode": "run", "accounts": {}, "user_name": "offline"},
                        "trade": {}, "subscribed": [], "draw_chart_datas": {}, "snapshots": {}}
        if initial_data:
            helper._data.update(initial_data)
        if probe:
            from aiohttp import web

            def index(request):
                html = (Path(tqsdk.__file__).parent / "web/index.html").read_text("utf-8")
                script = '''<script>
                // 阻止原生前端尝试外连；离线测试只接收本机 fixture。
                const NativeSocket=window.WebSocket;
                window.__fixtureChartRequests={};
                window.WebSocket=function(url,protocols){
                  if(new URL(url,location.href).hostname==='127.0.0.1')
                    return protocols?new NativeSocket(url,protocols):new NativeSocket(url);
                  return Object.assign(new EventTarget(),{readyState:0,
                    send(){},close(){this.readyState=3}});
                };
                Object.assign(window.WebSocket,{CONNECTING:0,OPEN:1,CLOSING:2,CLOSED:3});
                (window.webpackJsonp=window.webpackJsonp||[]).push([['offline-chart-wire'],{
                  'offline-chart-wire':function(module,exports,require){
                    const proto=require('0977').a.prototype,original=proto.setChart;
                    function capture(options){const result=original.call(this,options);
                      const packet=this.quotesWs.charts[options.chart_id];
                      if(packet)window.__fixtureChartRequests[packet.chart_id]={...packet};
                      return result;
                    }
                    proto.setChart=proto.set_chart=capture;
                  }},[['offline-chart-wire','chunk-vendors']]]);
                // 模拟行情服务确认 set_chart；价格仍只来自本机测试数据。
                setInterval(()=>{const view=document.querySelector('.tq-top-view')?.__vue__;
                  const sdk=view?.$tqsdk;
                  const series=sdk?.get_by_path(['klines',view.instrumentId,view.duration]);
                  const chart=sdk?.getChart('web_chart');
                  const request=window.__fixtureChartRequests.web_chart;
                  const fields=['ins_list','duration','view_width','left_kline_id',
                    'focus_datetime','focus_position','trading_day_start','trading_day_count'];
                  const matches=chart?.state&&request&&fields.every(k=>
                    (k in request)===(k in chart.state)&&
                    (!(k in request)||request[k]===chart.state[k]));
                  if(!chart||!series||series.last_id<0||request?.ins_list!==view.instrumentId||
                    request?.duration!==view.duration||
                    (chart.more_data===false&&matches))return;
                  const replyState={...request};
                  for(const key of fields)
                    if(!(key in request)&&key in chart.state)replyState[key]=null;
                  const last=series.data[series.last_id];
                  sdk.dm.mergeData({charts:{web_chart:{more_data:false,left_id:0,right_id:series.last_id,
                    state:replyState}},klines:{[view.instrumentId]:{
                    [view.duration]:{data:{[series.last_id]:{close:last.close===3305?3306:3305}}}}}});
                },100);
                setInterval(()=>parent.postMessage({kind:'offline-native-probe',
                  text:document.body.innerText, bridge:!!window.pywebview?.api,
                  selected:document.querySelector('.tq-top-view .title')?.textContent,
                  original:document.querySelector('.tq-top-view .title')?.title,
                  layout:(()=>{
                    const left=document.querySelector('.tq-top-view .left-view');
                    if(!left)return null;
                    const toolbar=left.children[0],chart=left.children[1];
                    const controls=[toolbar.querySelector('.title'),
                      toolbar.querySelector('.tq-button-group-durations'),
                      toolbar.querySelector('.ivu-checkbox-wrapper')];
                    const view=document.querySelector('.tq-top-view')?.__vue__;
                    const canvases=[...left.querySelectorAll('canvas')];
                    return {width:innerWidth,
                      plotWidth:Math.max(0,...canvases.map(c=>c.clientWidth)),
                      rootWidth:view?.$root?.windowWidth,chartWidth:view?.chartWidth,
                      chartTop:chart.getBoundingClientRect().top,
                      bottoms:controls.map(e=>e?.getBoundingClientRect().bottom)};
                  })()},'*'),100);
                addEventListener('message',event=>{
                  if(event.data?.kind==='offline-native-click')
                    document.querySelectorAll('.subscribed-list button')[1]?.click();
                  if(event.data?.kind==='offline-native-period')
                    [...document.querySelectorAll('.ivu-radio-wrapper')]
                      .find(item=>item.textContent.trim()==='30分钟')?.click();
                });</script>'''
                return web.Response(text=html.replace("<head>", "<head>" + script
                                                     + "<script>" + extra_script + "</script>"),
                                    content_type="text/html")

            helper.httpserver_index_handler = index
        helper._conn_diff_chans = set()
        helper._http_server_host = "127.0.0.1"
        helper._http_server_port = int(address.rsplit(":", 1)[1])
        helper._web_dir = str(Path(tqsdk.__file__).parent / "web")
        task = asyncio.create_task(helper.link_httpserver())
        try:
            revision = -1
            while not stop.is_set():
                await asyncio.sleep(0.05)
                if probe and initial_data is not None:
                    current = initial_data.get("_fixture_revision", 0)
                    if current != revision:
                        revision = current
                        for channel in tuple(helper._conn_diff_chans):
                            await channel.send({"klines": initial_data.get("klines", {})})
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
            window.create_confirmation_dialog = lambda *args: True

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
