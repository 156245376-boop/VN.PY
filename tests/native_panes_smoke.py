"""四个真实原生图表独立周期/身份检查；只使用本机合成数据。"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402
from window_smoke import address, fixture_klines, ready, serve, stop  # noqa: E402

from qf.window_host import run_window  # noqa: E402

TOOLS_PROBE = '''const attachProbe=setInterval(()=>{
  const tools=window.QfNativeTools;if(!tools)return;
  if(!tools.fixtureHook){tools.fixtureHook=true;const attach=tools.attach;
    tools.attach=function(chart){window.fixtureChart=chart;return attach(chart)};}
  if(window.fixtureChart)clearInterval(attachProbe);
  else document.querySelector('.tq-top-view')?.__vue__?.$refs?.tqChart?.updateTqChart();
},50);
addEventListener('message',event=>{
  if(event.data?.kind==='offline-draw'){
    const canvas=window.fixtureChart.mainBoard._centerTopCanvas.dom;
    const box=canvas.getBoundingClientRect();QfNativeTools.select('horizontal');
    canvas.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,buttons:1,clientX:box.left+box.width/2,clientY:box.top+box.height/2}));
    canvas.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0,buttons:0,clientX:box.left+box.width/2,clientY:box.top+box.height/2}));
  }
  if(event.data?.kind==='offline-tools-inspect')parent.postMessage({kind:'offline-tools-result',items:QfNativeTools.exportDrawings(event.data.symbol),inspect:QfNativeTools.inspect(),tick:window.fixtureChart?.price_ticks},'*');
});'''


def exercise():
    data = {'subscribed': [{'symbol': 'SHFE.rb2701', 'dur_nano': 60000000000}], 'klines': {}}
    for symbol in ('SHFE.rb2701', 'DCE.m2701'):
        for seconds in (60, 300, 900, 1800, 3600, 86400):
            value = fixture_klines(symbol, seconds * 1_000_000_000)
            data['klines'].setdefault(symbol, {}).update(value[symbol])
    server = threading.Thread(target=lambda: serve(data, probe=True, extra_script=TOOLS_PROBE),
                              daemon=True)
    server.start()
    assert ready.wait(5)
    errors = []
    with tempfile.TemporaryDirectory() as temp:
        page = Path(temp) / 'index.html'
        html = '''<body style="display:grid;grid-template-columns:1fr 1fr;margin:0">
        <script>const frames=[],states={},tools={};const book=QfDrawingBook.create();
        function configure(index,period,revision){const f=frames[index];
          f.binding={pane_id:'pane-'+(index+1),generation:5,revision};
          f.contentWindow.postMessage({kind:'qf-chart-labels',pane_id:'pane-'+(index+1),
            generation:5,revision,catalog:[],symbol:index===3?'DCE.m2701':'SHFE.rb2701',
            period,compact:true},ADDRESS)}
        addEventListener('message',e=>{const i=frames.findIndex(f=>f.contentWindow===e.source);
          if(i<0)return;if(e.data.kind==='qf-chart-ready')configure(i,['1m','5m','1h','1d'][i],10+i);
          if(e.data.kind==='qf-chart-state')states[i]=e.data;
          if(e.data.kind==='offline-tools-result'){tools[i]=e.data.items;window.lastTool=e.data;}
          if(['qf-drawings-request','qf-drawings-commit','qf-drawings-undo'].includes(e.data.kind)){
            const d=e.data,result=d.kind==='qf-drawings-request'?book.read(d.symbol):
              d.kind==='qf-drawings-undo'?book.undo(d.symbol,d.version):book.commit(d.symbol,d.version,d.drawings);
            for(let j=0;j<frames.length;j++)if(i===j||(d.kind!=='qf-drawings-request'&&states[j]?.symbol===d.symbol))
              frames[j].contentWindow.postMessage({kind:'qf-drawings-state',...result,symbol:d.symbol,
                source_pane:d.kind==='qf-drawings-request'?null:d.pane_id,...frames[j].binding},ADDRESS);
          }});
        addEventListener('qf-native-labels-ready',()=>{for(let i=0;i<4;i++){
          const f=document.createElement('iframe');f.style='width:100%;height:350px;border:0';
          f.src=ADDRESS;frames.push(f);document.body.append(f);}});</script></body>'''
        drawing_source = (Path(__file__).parents[1] / 'qf/web/chart-drawings.js').read_text('utf-8')
        page.write_text('<script>' + drawing_source + '</script>' +
                        html.replace('ADDRESS', json.dumps(address)), encoding='utf-8')
        original = webview.create_window

        def create(*args, **kwargs):
            kwargs['hidden'] = True
            window = original(*args, **kwargs)
            window.create_confirmation_dialog = lambda *args: True

            def check(js):
                end = time.monotonic() + 12
                while time.monotonic() < end:
                    if window.evaluate_js(js):
                        return
                    time.sleep(.05)
                raise AssertionError(js + ' ' + str(window.evaluate_js('states')))

            def interact():
                try:
                    print('PANES_STAGE starting', flush=True)
                    check('Object.keys(states).length===4&&Object.values(states).every(s=>s.status==="ready")')
                    print('PANES_STAGE ready', flush=True)
                    observed = window.evaluate_js('Object.values(states)')
                    assert [s['pane_id'] for s in observed] == [f'pane-{i}' for i in range(1, 5)]
                    assert [s['duration'] for s in observed] == [60000000000, 300000000000,
                                                               3600000000000, 86400000000000]
                    assert all(s['generation'] == 5 for s in observed)
                    window.evaluate_js('configure(1,"15m",30)')
                    check('states[1].revision===30&&states[1].duration===900000000000&&states[1].status==="ready"')
                    assert window.evaluate_js('states[0].revision===10&&states[2].revision===12&&states[3].revision===13')
                    window.evaluate_js('configure(1,"close",31)')
                    check('states[1].revision===31&&states[1].duration===60000000000')
                    print('PANES_STAGE close-period', flush=True)
                    window.evaluate_js("frames[0].contentWindow.postMessage({kind:'offline-draw'},'*')")
                    print('PANES_STAGE draw-sent', flush=True)
                    window.evaluate_js("frames[0].contentWindow.postMessage({kind:'offline-tools-inspect',symbol:'SHFE.rb2701'},'*')")
                    time.sleep(.2)
                    print('PANES_TOOLS ' + str(window.evaluate_js('({lastTool,book:book.read("SHFE.rb2701")})')), flush=True)
                    check("book.read('SHFE.rb2701').version===1")
                    window.evaluate_js("frames.forEach(f=>f.contentWindow.postMessage({kind:'offline-tools-inspect',symbol:'SHFE.rb2701'},'*'))")
                    check('Object.keys(tools).length===4&&tools[0].length===1&&tools[2].length===1')
                    assert window.evaluate_js('JSON.stringify(tools[0])===JSON.stringify(tools[2])')
                    assert window.evaluate_js('tools[3].length===0')
                except Exception as exc:
                    errors.append(str(exc))
                    print('PANES_ERROR ' + str(exc), flush=True)
                finally:
                    print('PANES_STAGE closing', flush=True)
                    window.destroy()
                    print('PANES_STAGE closed', flush=True)

            window.events.loaded += lambda: threading.Thread(target=interact).start()
            return window

        webview.create_window = create
        try:
            run_window(page, object(), lambda: True)
        finally:
            stop.set()
            server.join(4)
    assert not errors, errors
    print('NATIVE_PANES_OK')


if __name__ == '__main__':
    exercise()
