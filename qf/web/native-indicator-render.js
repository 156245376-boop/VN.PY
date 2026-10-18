// 复用锁定原生 chart.addSeries、board、坐标和 canvas；VP 为独立透明图层。
(() => {
  'use strict';const attached=new WeakMap();
  const names={ma:'简单均线',ema:'指数均线',boll:'布林带',sar:'抛物线',macd:'MACD',kdj:'KDJ',rsi:'RSI',atr:'真实波幅',cci:'CCI',dmi:'DMI',obv:'能量潮',volume:'成交量',oi:'持仓量'};
  const periodName=p=>({'1m':'1分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','1h':'1小时','1d':'日线',close:'分时'}[p]||p);
  function lineData(points,source){const data=[];for(const p of points||[])
    if(Number.isFinite(p.value)&&String(Math.trunc(source[p.id]?.datetime))===p.time_ns)
      data[p.id]={value:p.value,datetime:source[p.id].datetime};return data;}
  function heat(r){const stops=[[40,110,205],[240,205,55],[240,125,35],[220,45,40]],n=Math.min(2,Math.floor(r*3)),t=r*3-n;
    return 'rgb('+stops[n].map((v,i)=>Math.round(v+(stops[n+1][i]-v)*t)).join(',')+')';}
  function profileGeometry(profile,style,width,scale){const max=Math.max(...profile.bins.map(b=>b.volume),0);
    return profile.bins.filter(b=>b.volume>0).map(b=>{const r=b.volume/max,w=width*style.width_pct/100*r;
      return {...b,x:style.side==='right'?width-w:0,y:Math.min(scale(b.high),scale(b.low)),
        height:Math.max(1,Math.abs(scale(b.high)-scale(b.low))),width:w,fill:heat(r),opacity:1-style.transparency/100};});}
  function attach(chart){if(attached.has(chart))return attached.get(chart);
    const originalDraw=chart.draw,table=chart.tableContainer,originalUpdate=table.update,
      originalPlots={volume:chart.plots.volume,oi:chart.plots.oi},originalSub=chart.boards.sub;
    let settings={items:[]},info={priceUnit:'报价单位'},result={series:[],profiles:[],issues:[]},alive=true,enabled=true,busy=false,key='',managed=new Set();
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('qf-vp');
    Object.assign(svg.style,{position:'absolute',inset:'0',pointerEvents:'none',zIndex:'2',overflow:'hidden'});
    const parent=chart.mainBoard._centerTopCanvas.dom.parentElement;parent.style.position='relative';parent.append(svg);
    const label=document.createElement('div');label.className='qf-indicator-note';
    Object.assign(label.style,{position:'absolute',top:'3px',left:'5px',zIndex:'3',fontSize:'10px',color:'#577064',pointerEvents:'none',maxWidth:'95%',background:'#ffffffbb'});parent.append(label);
    const handles=new Map();
    function removePlots(){for(const id of managed)delete chart.plots[id];managed.clear();}
    function layout(){if(!alive)return;const boards=table.boards,sub=boards.filter(b=>b.boardId!=='main');
      const heights=sub.map(b=>{const id=b.boardId.replace(/^qf_/,''),item=settings.items.find(i=>i.id===id||id==='volume_oi'&&['volume','oi'].includes(i.type));return item?.height||160;});
      const main=Math.max(260,chart.height-chart.margin.bottom-heights.reduce((a,b)=>a+b,0)-sub.length);
      chart.rootContainer.style.overflow='auto';table.root.style.height=(main+heights.reduce((a,b)=>a+b,0)+sub.length+chart.margin.bottom)+'px';
      for(const [i,b]of boards.entries()){const height=b.boardId==='main'?main:heights[sub.indexOf(b)];
        if(b.height!==height||b.width!==chart.width)b.update({width:chart.width,height});
        if(b.boardId!=='main'&&!handles.has(b)){
          const handle=b._rootElement.dom.previousSibling?.querySelector?.('.handle');if(!handle)continue;
          handle.style.cursor='row-resize';handle.title='上下拖动调整指标副图高度';
          const down=e=>{if(e.button!==0)return;e.preventDefault();e.stopPropagation();const start=e.clientY,old=b.height;handle.setPointerCapture(e.pointerId);
            const item=settings.items.find(x=>'qf_'+x.id===b.boardId||b.boardId==='qf_volume_oi'&&['volume','oi'].includes(x.type));
            if(!item)return;let changed=old;
            const move=ev=>{changed=Math.round(Math.max(120,Math.min(600,old-(ev.clientY-start))));item.height=changed;layout();chart.draw();};
            const up=()=>{handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',up);handle.removeEventListener('pointercancel',up);api.onHeight?.(item.id,changed);};
            handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',up);handle.addEventListener('pointercancel',up);};
          handle.addEventListener('pointerdown',down);handles.set(b,{handle,down});
        }
      }
    }
    function trimBoards(wanted){for(const name of Object.keys(chart.boards))if(name.startsWith('qf_')&&!wanted.has(name)){
      const b=chart.boards[name],h=handles.get(b);if(h){h.handle.removeEventListener('pointerdown',h.down);handles.delete(b);}table.deleteBoard(name);delete chart.boards[name];}}
    function patchPlot(plot,bars){
      plot.getYDomain=function(left,right,data){const values=data.slice(left,right+1).filter(Boolean).map(p=>p.value);if(!values.length)return [Infinity,-Infinity];
        let lo=Math.min(...values),hi=Math.max(...values);if(bars){lo=Math.min(0,lo);hi=Math.max(0,hi);}const pad=(hi-lo)*.1||Math.max(1,Math.abs(hi)*.01);return [lo-pad,hi+pad];};
      plot.draw=function(ctx,left,right,input){const data=input||this.data,dpr=window.devicePixelRatio||1;ctx.save();ctx.strokeStyle=this.color;ctx.fillStyle=this.color;ctx.lineWidth=this.width*dpr;ctx.beginPath();let last=null;
        for(let id=left;id<=right;id++){const p=data[id];if(!p||!Number.isFinite(p.value)){last=null;continue;}
          const x=(id*chart.bar.step+chart.bar.barWidth/2)*dpr,y=this.yScale(p.value)*dpr;
          if(bars){ctx.fillStyle=p.value>=0?'#d9504e':'#2c936b';const base=this.yScale(0)*dpr;ctx.fillRect(id*chart.bar.step*dpr,Math.min(y,base),Math.max(1,chart.bar.barWidth*dpr),Math.max(1,Math.abs(base-y)));}
          else{if(last===id-1)ctx.lineTo(x,y);else ctx.moveTo(x,y);last=id;}}
        if(!bars)ctx.stroke();ctx.restore();};
    }
    function build(){if(!alive||busy)return;busy=true;try{
      removePlots();delete chart.plots.volume;delete chart.plots.oi;
      if(chart.boards.sub){table.deleteBoard('sub');delete chart.boards.sub;}
      const wanted=new Set();
      if(key===chart.symbol+'|'+chart.duration)for(const series of result.series||[]){const item=settings.items.find(i=>i.id===series.item_id&&i.visible);if(!item)continue;
        const data=lineData(series.points,chart.mainSeries.data),board=series.board==='main'?'main':['volume','oi'].includes(item.type)?'qf_volume_oi':'qf_'+item.id;
        if(board!=='main')wanted.add(board);
        const id='qf_'+item.id+'_'+series.name;const index=(result.series||[]).filter(x=>x.item_id===item.id).indexOf(series);
        chart.addSeries(id,{type:'SERIAL',board,style:'LINE',yAlign:item.type==='oi'?'left':'right',data,
          color:item.style.colors[index%item.style.colors.length],width:item.style.width});
        const plot=chart.plots[id];if(!plot)continue;plot.data=data;plot.plotId=(names[item.type]||item.type.toUpperCase())+' '+series.name+'（'+(series.unit==='价格'?info.priceUnit:series.unit==='指标值'?'无量纲':series.unit)+'）';
        patchPlot(plot,item.type==='volume'||item.type==='macd'&&series.name==='bar');managed.add(id);
      }
      trimBoards(wanted);layout();
    }finally{busy=false;}chart.draw();}
    function paint(){if(!alive)return;svg.replaceChildren();const canvas=chart.mainBoard._centerTopCanvas.dom,w=canvas.clientWidth,h=canvas.clientHeight;
      svg.setAttribute('width',w);svg.setAttribute('height',h);
      label.textContent=enabled?(result.issues||[]).map(i=>i.reason).join('；')||((result.profiles||[]).length?'VP 估算 · 按收盘价归集 · '+chart.duration/1e9+'秒；':'')+(result.warmup||''):'';
      if(key!==chart.symbol+'|'+chart.duration)return;
      const scale=chart.mainBoard.rightYAxis.scale;
      for(const profile of result.profiles||[]){const item=settings.items.find(i=>i.id===profile.item_id&&i.visible);if(!item)continue;
        for(const b of profileGeometry(profile,item.style,w,scale)){
          const rect=document.createElementNS(ns,'rect');for(const k of ['x','y','width','height','fill','opacity'])rect.setAttribute(k,b[k]);
          const title=document.createElementNS(ns,'title');title.textContent=`VP 估算 · ${periodName(profile.period)} · ${b.low}–${b.high} ${info.priceUnit} · ${b.volume} 手 · ${(b.share*100).toFixed(2)}%`;
          rect.append(title);rect.style.pointerEvents='visiblePainted';svg.append(rect);}
        if(item.style.poc){const line=document.createElementNS(ns,'line');for(const [k,v]of Object.entries({x1:0,x2:w,y1:scale(profile.poc),y2:scale(profile.poc),stroke:'#d9504e','stroke-dasharray':'4 3'}))line.setAttribute(k,v);svg.append(line);}
      }
    }
    table.update=function(...args){originalUpdate.apply(this,args);if(alive)layout();};
    chart.draw=function(...args){if(busy)return;layout();const values=[];for(const id of managed){const p=chart.plots[id];if(p?.boardId==='main')for(let i=chart.chartCtrl.range.leftId;i<=chart.chartCtrl.range.rightId;i++)if(Number.isFinite(p.data[i]?.value))values.push(p.data[i].value);}
      QfNativeTools.setIndicatorPriceExtent?.(chart,values.length?[Math.min(...values),Math.max(...values)]:null);
      const value=originalDraw.apply(this,args);paint();return value;};
    const api={chart,onHeight:null,configure(next,on=true,metadata){settings=JSON.parse(JSON.stringify(next));if(metadata)info=metadata;enabled=on;if(!enabled)result={series:[],profiles:[],issues:[]};build();},
      apply(next,nextSettings){result=next||{series:[],profiles:[],issues:[]};settings=JSON.parse(JSON.stringify(nextSettings));key=chart.symbol+'|'+chart.duration;build();},
      clear(id){result.series=(result.series||[]).filter(s=>s.item_id!==id);result.profiles=(result.profiles||[]).filter(s=>s.item_id!==id);build();},
      dispose(){if(!alive)return;alive=false;removePlots();for(const {handle,down}of handles.values())handle.removeEventListener('pointerdown',down);handles.clear();
        chart.draw=originalDraw;table.update=originalUpdate;trimBoards(new Set());
        if(!chart.boards.sub&&originalSub){chart.boards.sub=originalSub;table.addBoard(originalSub);}Object.assign(chart.plots,originalPlots);svg.remove();label.remove();attached.delete(chart);}};
    attached.set(chart,api);return api;
  }
  window.QfNativeIndicatorRender={attach,profileGeometry,lineData};
})();
