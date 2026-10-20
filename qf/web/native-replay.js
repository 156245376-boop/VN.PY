// 离线成交覆盖层复用SDK图表与坐标；时间用BigInt映射，避免纳秒精度丢失。
(() => {
  'use strict';
  function barForTime(bars,time,seconds){const t=BigInt(time);let lo=0,hi=bars.length-1,found=-1;
    while(lo<=hi){const mid=(lo+hi)>>1;if(BigInt(bars[mid].time_ns)<=t){found=mid;lo=mid+1;}else hi=mid-1;}
    if(found<0)return null;
    const end=bars[found].end_ns?BigInt(bars[found].end_ns):found+1<bars.length?BigInt(bars[found+1].time_ns):BigInt(bars[found].time_ns)+BigInt(seconds)*1000000000n;
    return t<end?found:null;}
  function protectionGeometry(segments,bars,seconds){if(!bars?.length)return [];
    const first=BigInt(bars[0].time_ns),last=BigInt(bars.at(-1).end_ns||bars.at(-1).time_ns);
    return (segments||[]).map(s=>{let a=barForTime(bars,s.start_ns,seconds),b=barForTime(bars,s.end_ns,seconds);
      if(a===null&&BigInt(s.start_ns)<=first)a=0;if(b===null&&BigInt(s.end_ns)>=last)b=bars.length-1;
      if(a===null||b===null||b<a)return null;const price=Number(s.display_price);
      return Number.isFinite(price)?{a,b,price,kind:s.kind,trade_id:s.trade_id,actual_price:s.actual_price,source_symbol:s.source_symbol}:null;
    }).filter(Boolean);}
  function timeAtRight(chart,payload){const range=chart?.chartCtrl?.range;if(!range||!payload?.bars?.length)return null;
    const index=Math.max(0,Math.min(payload.bars.length-1,Number(range.rightId)-(payload.first_bar_id||0)));
    return payload.bars[index]?.time_ns||null;}
  const fillName=f=>f.direction==='BUY'?(f.offset==='OPEN'?'买开（做多）':'买平（平空）'):(f.offset==='OPEN'?'卖开（做空）':'卖平（平多）');
  const acceptMessage=(e,parent,origin,run,revision)=>e.source===parent&&e.origin===origin&&e.data?.run_id===run&&e.data?.revision===revision;
  function attach(chart,options={}){
    const canvas=chart.mainBoard._centerTopCanvas.dom,parent=canvas.parentElement,ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    Object.assign(svg.style,{position:'absolute',inset:0,zIndex:4,pointerEvents:'none',overflow:'hidden'});parent.style.position='relative';parent.append(svg);
    let payload=null,alive=true;const original=chart.draw;
    const x=id=>(id+(payload?.first_bar_id||0))*chart.bar.step-chart.chartCtrl.pixelLeft+chart.bar.step/2;
    function shape(tag,attrs){const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);svg.append(e);return e;}
    function paint(){if(!payload||!alive)return;svg.replaceChildren();svg.setAttribute('width',canvas.clientWidth);svg.setAttribute('height',canvas.clientHeight);
      const y=chart.mainBoard.rightYAxis.scale;
      for(const f of payload.fills){const id=barForTime(payload.bars,f.time_ns,payload.bar_seconds);if(id===null)continue;
        const px=x(id),py=y(Number(f.display_price??f.price)),up=f.direction==='BUY';
        const marker=shape('path',{d:up?`M${px},${py-8}l-6,12h12Z`:`M${px},${py+8}l-6,-12h12Z`,fill:up?'#d24e48':'#168669','data-fill':f.key});
        marker.style.pointerEvents='all';marker.style.cursor='pointer';const title=document.createElementNS(ns,'title');title.textContent=fillName(f)+' · '+f.volume+' 手 · 成交价 '+f.price;marker.append(title);
        marker.onclick=()=>options.onFill?.(f);}
      const events=payload.risk_events||[];
      for(const roll of payload.main_changes||[]){const id=barForTime(payload.bars,roll.time_ns,payload.bar_seconds);if(id===null||!roll.old_symbol)continue;
        const line=shape('line',{x1:x(id),x2:x(id),y1:0,y2:canvas.clientHeight,stroke:'#9267b6','stroke-dasharray':'3 3'});
        const title=document.createElementNS(ns,'title');title.textContent='主力换月：'+roll.old_symbol+' → '+roll.new_symbol;line.append(title);}
      const traces=payload.protection?.segments?.length?protectionGeometry(payload.protection.segments,payload.bars,payload.bar_seconds):[];
      for(const line of traces){const node=shape('line',{x1:x(line.a),x2:x(line.b),y1:y(line.price),y2:y(line.price),
        stroke:line.kind==='initial'?'#d0902a':'#a57724','stroke-dasharray':line.kind==='initial'?'6 3':'4 3','data-protection':line.kind});
        const title=document.createElementNS(ns,'title');title.textContent=(line.kind==='initial'?'初始止损':'当前保护')+' · 实际 '+line.actual_price+' · '+line.source_symbol;node.append(title);}
      if(!traces.length)for(let i=0;i<events.length;i++){const e=events[i],r=e.risk;if(!r?.quantity||!Number(r.stop_price)||e.kind==='stopped')continue;
        const next=events[i+1];if(!next||next.risk?.trade_id!==r.trade_id)continue;
        const a=barForTime(payload.bars,e.time_ns,payload.bar_seconds),b=barForTime(payload.bars,next.time_ns,payload.bar_seconds);
        if(a===null||b===null)continue;
        shape('line',{x1:x(a),x2:x(b),y1:y(Number(r.stop_price)),y2:y(Number(r.stop_price)),stroke:'#a57724','stroke-dasharray':'4 3','data-protection':r.stage});}
    }
    chart.draw=function(...args){const result=original.apply(this,args);paint();options.onTime?.(timeAtRight(chart,payload));return result;};
    function apply(next){if(payload&&(payload.run_id!==next.run_id||payload.revision!==next.revision))return false;payload=next;
      for(const [i,line]of payload.ma_series.entries()){const data=[];for(const p of line.points)data[p.id]={value:p.value,datetime:Number(BigInt(p.time_ns))};
        const id='qf_replay_ma_'+i;chart.addSeries(id,{type:'SERIAL',board:'main',style:'LINE',yAlign:'right',data,color:i?'#cf862e':'#437cc5',width:2});
        if(chart.plots[id]){chart.plots[id].data=data;chart.plots[id].plotId='简单均线 MA('+line.period+')';}}
      chart.draw();return true;}
    return {apply,focusFill(key){const f=payload?.fills.find(f=>f.key===key);if(!f)return false;
      const id=barForTime(payload.bars,f.time_ns,payload.bar_seconds);if(id===null)return false;const offset=payload.first_bar_id||0;chart.setRange(offset+Math.max(0,id-25),offset+Math.min(payload.bars.length-1,id+25));chart.draw();options.onFill?.(f);return true;},
      dispose(){alive=false;chart.draw=original;svg.remove();}};
  }
  globalThis.QfNativeReplay={attach,barForTime,fillName,acceptMessage,protectionGeometry,timeAtRight};
  if(typeof window==='undefined'||!window.__qfReplay)return;
  let layer=null,payload=null,loaded=false,chart=null,dataInstalled=false,lastRequestKey='',accountAt='',accountRequest=0;
  const banner=document.createElement('div');banner.className='qf-replay-banner';banner.textContent='离线复盘 · 正在读取本机结果（不是实时行情）';document.body.prepend(banner);
  let parentOrigin=null;try{parentOrigin=new URL(document.referrer).origin;}catch(_){}
  const emit=f=>{if(parentOrigin)parent.postMessage({kind:'qf-replay-fill',run_id:payload.run_id,revision:payload.revision,fill:f},parentOrigin);};
  async function emitAccount(stamp){
    if(!parentOrigin||!payload||!stamp||stamp===accountAt)return;accountAt=stamp;const token=++accountRequest;
    try{const response=await fetch('/account?time_ns='+encodeURIComponent(stamp),{cache:'no-store'});const packet=await response.json();
      if(token!==accountRequest||!packet.account)return;parent.postMessage({kind:'qf-research-account',run_id:payload.run_id,revision:payload.revision,time_ns:stamp,account:packet.account},parentOrigin);
    }catch(_){}}
  async function load(){payload=await(await fetch('/replay')).json();payload.bars=[];let offset=0;
    while(true){const page=await(await fetch('/bars?offset='+offset+'&limit=10000')).json();if(!page.bars?.length)throw Error('复盘数据缺页');
      payload.bars.push(...page.bars);offset=page.next_offset;banner.textContent='离线复盘 · 已加载 '+offset+' / '+page.total_bars+' 根保存K线';if(offset>=page.total_bars)break;}
    loaded=true;}
  load().catch(()=>{banner.textContent='离线复盘读取失败；没有使用当前行情补造数据。';});
  const timer=setInterval(()=>{if(!loaded)return;const view=document.querySelector('.tq-top-view')?.__vue__,sdk=view?.$tqsdk;if(!sdk)return;
    const symbol=payload.symbol,duration=payload.bar_seconds*1e9,request=window.__replayRequests.web_chart;
    if(view.instrumentId!==symbol||view.duration!==duration){view.instrumentId=symbol;view.duration=duration;return;}
    if(request&&request.ins_list===symbol&&request.duration===duration){
      const existing=sdk.get_by_path(['klines',symbol,duration]),needData=!dataInstalled||existing?.last_id!==payload.bars.length-1,key=JSON.stringify(request);
      if(needData||key!==lastRequestKey){const state={...request},previous=sdk.getChart('web_chart')?.state||{};
        for(const field of ['ins_list','duration','view_width','left_kline_id','focus_datetime','focus_position','trading_day_start','trading_day_count'])if(!(field in request)&&field in previous)state[field]=null;
        const diff={charts:{web_chart:{state,more_data:false,left_id:0,right_id:payload.bars.length-1}}};
        if(needData){const data={};for(const [i,row]of payload.bars.entries())data[i]={...row,datetime:Number(BigInt(row.time_ns))};
          diff.klines={[symbol]:{[duration]:{data,last_id:payload.bars.length-1}}};dataInstalled=true;}
        lastRequestKey=key;sdk.dm.mergeData(diff);}}
    const next=window.QfNativeHistory?.getChart?.();if(!next||next.symbol!==symbol||next.duration!==duration)return;
    if(next!==chart){layer?.dispose();chart=next;layer=attach(chart,{onFill:emit,onTime:emitAccount});layer.apply(payload);
      if(parentOrigin)parent.postMessage({kind:'qf-replay-ready',run_id:payload.run_id,revision:payload.revision},parentOrigin);
      banner.textContent='离线复盘 · '+(payload.config.name||'双均线')+' · '+payload.bars.length+' 根保存K线（末根可能为形成柱，信号只用完成柱） · '+(payload.precision==='tick'?'Tick':'分钟近似')+' · 点击成交箭头查看原因';}
  },150);
  addEventListener('message',e=>{if(!payload||!acceptMessage(e,parent,parentOrigin,payload.run_id,payload.revision))return;
    if(e.data.kind==='qf-replay-focus'){layer?.focusFill(e.data.fill_id);if(e.data.time_ns)emitAccount(String(e.data.time_ns));}});
  addEventListener('pagehide',()=>{clearInterval(timer);layer?.dispose();});
})();
