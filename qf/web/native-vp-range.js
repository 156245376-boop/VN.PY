// 固定 VP 的时间选区，复用既有柱边界与鼠标模式；不修改普通研究画线。
(() => {
  'use strict';const instances=new WeakMap();
  function rangeForIntervals(symbol,a,b){return {symbol,start_ns:String(Math.trunc(Math.min(a.start,b.start))),end_ns:String(Math.trunc(Math.max(a.end,b.end)))};}
  function attach(chart,options={}){if(instances.has(chart)){const api=instances.get(chart);api.onChange=options.onChange;return api;}
    const canvas=chart.mainBoard._centerTopCanvas.dom,parent=canvas.parentElement,ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.classList.add('qf-vp-range');
    Object.assign(svg.style,{position:'absolute',inset:0,pointerEvents:'none',zIndex:'3',overflow:'hidden'});parent.append(svg);
    const badge=document.createElement('button');badge.textContent='VP 选区：点击两个时间位置 · 取消（Esc）';badge.hidden=true;
    Object.assign(badge.style,{position:'absolute',top:'40px',left:'8px',zIndex:'8',fontSize:'11px',color:'#196c57'});parent.append(badge);
    const ranges=new Map();let selecting=null,first=null,preview=null,editing=null,alive=true;
    function rowAt(x){const rows=QfNativeTools.intervals(chart),box=canvas.getBoundingClientRect();
      const id=Math.floor((Math.max(0,Math.min(box.width,x-box.left))+chart.chartCtrl.pixelLeft)/chart.bar.step);
      return rows.find(r=>r.id===id)||rows.reduce((a,b)=>Math.abs(b.id-id)<Math.abs(a.id-id)?b:a,rows[0]);}
    function xFor(time){const rows=QfNativeTools.intervals(chart);if(!rows.length)return null;
      const t=Number(BigInt(time)),r=rows.find(r=>t>=r.start&&t<r.end);
      let id;if(r)id=r.id+(t-r.start)/(r.end-r.start);else if(t===rows.at(-1).end)id=rows.at(-1).id+1;
      else id=t<rows[0].start?rows[0].id-1e6:rows.at(-1).id+1e6;
      return id*chart.bar.step-chart.chartCtrl.pixelLeft;}
    function paint(){if(!alive)return;svg.replaceChildren();svg.setAttribute('width',canvas.clientWidth);svg.setAttribute('height',canvas.clientHeight);
      const values=[...ranges];if(first&&preview)values.push(['preview',rangeForIntervals(chart.symbol,first,preview)]);
      for(const [id,r]of values){if(r.symbol!==chart.symbol)continue;const a=xFor(r.start_ns),b=xFor(r.end_ns);if(a===null||b===null)continue;
        const rect=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x:Math.min(a,b),y:1,width:Math.abs(b-a),height:Math.max(0,canvas.clientHeight-2),fill:'#418dab',opacity:.12,stroke:'#377a99'}))rect.setAttribute(k,v);svg.append(rect);
        if(id==='preview')continue;
        for(const [endpoint,x]of [['start_ns',a],['end_ns',b]]){const handle=document.createElementNS(ns,'circle');handle.setAttribute('cx',x);handle.setAttribute('cy',28);handle.setAttribute('r',6);handle.setAttribute('fill','#287a90');handle.style.pointerEvents='all';handle.style.cursor='ew-resize';
          handle.addEventListener('mousedown',e=>{if(e.button!==0)return;e.preventDefault();e.stopPropagation();QfNativeTools.cancelInteraction();editing={id,endpoint,before:{...r}};QfNativeTools.setExternalInteraction(chart,{cancel});});svg.append(handle);}
      }
    }
    function stop(){selecting=null;first=null;preview=null;badge.hidden=true;canvas.style.cursor='';QfNativeTools.setExternalInteraction(chart,null);paint();}
    function commit(id,r){ranges.set(id,r);api.onChange?.(id,{...r});paint();}
    function cancel(){if(editing)ranges.set(editing.id,editing.before);editing=null;stop();}
    function begin(id){cancel();QfNativeTools.cancelInteraction();selecting=id;badge.hidden=false;canvas.style.cursor='crosshair';
      QfNativeTools.setExternalInteraction(chart,{mousedown(e){if(e.button!==0)return true;const row=rowAt(e.clientX);if(!row)return true;
        if(!first){first=row;preview=row;paint();}else{const ident=selecting,r=rangeForIntervals(chart.symbol,first,row);stop();commit(ident,r);}return true;},
        mousemove(e){if(first){preview=rowAt(e.clientX);paint();}return true;},cancel});}
    const move=e=>{if(!editing)return;if(!(e.buttons&1)){cancel();return;}const row=rowAt(e.clientX);if(!row)return;
      const next={...ranges.get(editing.id)},value=String(Math.trunc(editing.endpoint==='start_ns'?row.start:row.end));next[editing.endpoint]=value;
      if(BigInt(next.start_ns)<BigInt(next.end_ns)){ranges.set(editing.id,next);paint();}};
    const up=()=>{if(!editing)return;const {id}=editing,r=ranges.get(id);editing=null;QfNativeTools.setExternalInteraction(chart,null);commit(id,r);};
    document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);addEventListener('blur',cancel);badge.onclick=cancel;
    const draw=chart.draw;chart.draw=function(...args){const value=draw.apply(this,args);paint();return value;};
    const api={chart,onChange:options.onChange,begin,cancel,setRange(id,r){if(r)ranges.set(id,{...r});else ranges.delete(id);paint();},
      configure(items){const ids=new Set(items.filter(i=>i.type==='vp'&&i.visible&&i.params.mode==='fixed').map(i=>i.id));for(const id of ranges.keys())if(!ids.has(id))ranges.delete(id);
        for(const i of items)if(i.type==='vp'&&i.visible&&i.params.mode==='fixed'&&i.params.range)ranges.set(i.id,{...i.params.range});paint();},
      locate(id){const r=ranges.get(id);if(r?.symbol===chart.symbol)QfNativeTools.focusTimeRange(chart,Number(BigInt(r.start_ns)),Number(BigInt(r.end_ns)));},
      dispose(){cancel();alive=false;document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up);removeEventListener('blur',cancel);chart.draw=draw;svg.remove();badge.remove();instances.delete(chart);}};
    instances.set(chart,api);return api;
  }
  window.QfNativeVpRange={attach,rangeForIntervals};
})();
