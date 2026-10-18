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
            const assertAuto=()=>{
              const domain=chart.mainBoard.rightYAxis.scale.domain();
              const shown=points=>points.filter(p=>p.id>=chart.range.leftId&&
                p.id<=chart.range.rightId&&Number.isFinite(p.value));
              const values=RESULT.series.filter(s=>s.board==='main')
                .flatMap(s=>shown(s.points).map(p=>p.value));
              if(values.some(v=>v<domain[0]||v>domain[1]))
                throw Error('自动价格域未包含主图指标 '+domain);
            };
            assertAuto();
            if(!window.QfNativeVpRange)throw Error('固定 VP 选区未接入');
            let selected=null;
            const ranges=QfNativeVpRange.attach(chart,{onChange:(id,r)=>selected=r});
            const canvas=chart.mainBoard._centerTopCanvas.dom,box=canvas.getBoundingClientRect();
            ranges.begin('vp-fixed');
            for(const x of [60,140])canvas.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true,button:0,buttons:1,clientX:box.left+x,clientY:box.top+50}));
            if(!selected||
              BigInt(selected.end_ns)<=BigInt(selected.start_ns))
              throw Error('固定 VP 两点选择未提交');
            const handle=document.querySelector('.qf-vp-range circle');
            if(!handle)throw Error('VP 编辑端点缺失');
            const old=selected.start_ns,hr=handle.getBoundingClientRect();
            handle.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,
              buttons:1,clientX:hr.left+3,clientY:hr.top+3}));
            document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,buttons:1,
              clientX:hr.left+30,clientY:hr.top+3}));
            document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0}));
            if(selected.start_ns===old)throw Error('VP 端点编辑没有改变时间');
            ranges.configure([{id:'vp-fixed',type:'vp',visible:true,params:{mode:'screen'}}]);
            if(document.querySelectorAll('.qf-vp-range circle').length)
              throw Error('屏幕模式仍保留固定区间端点');
            ranges.begin('vp-fixed');ranges.cancel();
            const before=chart.chartCtrl.pixelLeft;
            chart.chartCtrl.move(-20);chart.draw();
            const vp=document.querySelectorAll('.qf-vp rect').length;
            if(!vp)throw Error('VP 未绘制');
            assertAuto();
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
