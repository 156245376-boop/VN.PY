"""天勤原生绘图适配的离线集成；使用现有本机 fixture，不连接账户。"""

import json
import math
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402
from window_smoke import address, fixture_klines, ready, serve, stop  # noqa: E402

from qf.indicator_calculation import calculate_indicators  # noqa: E402
from qf.indicator_catalog import default_item  # noqa: E402
from qf.window_host import run_window  # noqa: E402


def exercise():
    klines = fixture_klines('SHFE.rb2701', 60_000_000_000)
    data = klines['SHFE.rb2701']['60000000000']['data']
    rows = []
    for key, row in data.items():
        row['close'] = 3300+math.sin(int(key)/5)*5
        rows.append(dict(id=int(key), time_ns=str(row['datetime']),
                    **{k: row[k] for k in ('open', 'high', 'low', 'close', 'volume', 'close_oi')}))
    settings = {'items': [default_item(k) for k in
                         ('volume', 'oi', 'ma', 'boll', 'macd', 'rsi', 'vp')]}
    result = calculate_indicators(dict(rows=rows, items=settings['items'], price_tick=1,
        symbol='SHFE.rb2701', period='1m', visible=[0, 219]))
    probe = """
      let tested=false;const timer=setInterval(()=>{
        if(tested||!window.QfNativeIndicatorRender||QfNativeHistory.inspect().status!=='ready')return;
        tested=true;clearInterval(timer);try{
          const chart=QfNativeHistory.getChart(),r=QfNativeIndicatorRender.attach(chart);
          r.configure(SETTINGS,true);r.apply(RESULT,SETTINGS);
          setTimeout(()=>{try{
            chart.draw();const boards=Object.keys(chart.boards).filter(k=>k.startsWith('qf_'));
            const plots=Object.keys(chart.plots).filter(k=>k.startsWith('qf_'));
            if(boards.length<2||plots.length<7)throw Error('指标主副图缺失 '+boards+'/'+plots);
            const initialDomain=chart.mainBoard.rightYAxis.scale.domain();
            const initialValues=RESULT.series.filter(s=>s.board==='main').flatMap(s=>s.points.filter(p=>p.id>=chart.range.leftId&&p.id<=chart.range.rightId&&Number.isFinite(p.value)).map(p=>p.value));
            if(initialValues.some(v=>v<initialDomain[0]||v>initialDomain[1]))throw Error('首次自动价格域未包含主图指标 '+initialDomain);
            const before=chart.chartCtrl.pixelLeft;
            chart.chartCtrl.move(-20);chart.draw();
            const vp=document.querySelectorAll('.qf-vp rect').length;
            if(!vp)throw Error('VP 未绘制');
            const domain=chart.mainBoard.rightYAxis.scale.domain();
            const shown=resultPoints=>resultPoints.filter(p=>p.id>=chart.range.leftId&&p.id<=chart.range.rightId&&Number.isFinite(p.value));
            const mainValues=RESULT.series.filter(s=>s.board==='main').flatMap(s=>shown(s.points).map(p=>p.value));
            if(mainValues.some(v=>v<domain[0]||v>domain[1]))throw Error('自动价格域未包含主图指标 '+domain);
            parent.postMessage({kind:'indicator-smoke',boards,plots:plots.length,vp,
              bridge:!!window.pywebview?.api,moved:chart.chartCtrl.pixelLeft!==before},'*');
          }catch(e){parent.postMessage({kind:'indicator-smoke',error:String(e)},'*');}},400);
        }catch(e){parent.postMessage({kind:'indicator-smoke',error:String(e)},'*');}
      },100);
    """.replace('SETTINGS', json.dumps(settings)).replace('RESULT', json.dumps(result))
    server = threading.Thread(target=lambda: serve({'klines': klines,
        'subscribed': [{'symbol': 'SHFE.rb2701', 'dur_nano': 60_000_000_000}]},
        probe=True, extra_script=probe), daemon=True)
    server.start()
    assert ready.wait(5)
    observed = {}
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp)/'index.html'
        page.write_text('''<html><body style="margin:0"><iframe id="chart"
          style="width:100%;height:780px;border:0"></iframe><script>
          window.probe=null;addEventListener('message',e=>{if(e.data?.kind==='indicator-smoke')window.probe=e.data});
          addEventListener('qf-native-labels-ready',()=>document.querySelector('#chart').src=ADDRESS);
          </script></body></html>'''.replace('ADDRESS', json.dumps(address)), encoding='utf-8')
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs['hidden'] = True
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *a: True

            def interact():
                try:
                    end = time.monotonic()+20
                    while time.monotonic() < end:
                        value = window.evaluate_js('window.probe')
                        if value:
                            observed.update(value)
                            break
                        time.sleep(.1)
                finally:
                    window.destroy()
            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            run_window(page, object(), lambda: True)
        finally:
            stop.set()
            server.join(5)
    assert observed and 'error' not in observed, observed
    assert observed['bridge'] is False
    print('NATIVE_INDICATORS_OK')


if __name__ == '__main__':
    exercise()
