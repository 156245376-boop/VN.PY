// 连续回测专用分页；稳定全局序号，过期异步结果不能覆盖新选择。
(() => {
  'use strict';
  class WindowCache {
    constructor(run){this.run=run;this.request=0;this.bars=[];}
    begin(series,symbol){this.series=series;this.symbol=symbol;return {run_id:this.run,series,actual_symbol:symbol,request_id:String(++this.request)};}
    accept(page){if(page.run_id!==this.run||page.series!==this.series||page.actual_symbol!==this.symbol||page.request_id!==String(this.request))return false;
      this.bars=page.bars.slice(-10000);return true;}
  }
  globalThis.QfContinuousReplay={WindowCache};
  if(typeof window==='undefined'||!window.__qfContinuousReplay)return;
  let header=null,cache=null,payload=null,chart=null,layer=null,installed=[],selection='signal',actual=null,busy=false,alive=true,requestKey='',accountTime='',accountRequest=0;
  let parentOrigin=null;try{parentOrigin=new URL(document.referrer).origin;}catch(_){}
  const banner=document.createElement('div');banner.className='qf-replay-banner';
  async function emitAccount(stamp){if(!parentOrigin||!header||!stamp||stamp===accountTime)return;accountTime=stamp;const token=++accountRequest;
    try{const response=await fetch('/account?time_ns='+encodeURIComponent(stamp),{cache:'no-store'});const packet=await response.json();
      if(token!==accountRequest||!packet.account)return;parent.postMessage({kind:'qf-research-account',run_id:header.run_id,revision:header.revision,time_ns:stamp,account:packet.account},parentOrigin);
    }catch(_){}}
  const label=document.createElement('span'),series=document.createElement('select'),date=document.createElement('input');date.type='date';
  const previous=document.createElement('button'),next=document.createElement('button'),locate=document.createElement('button');
  previous.textContent='前一窗口';next.textContent='后一窗口';locate.textContent='定位日期';
  banner.append(label,series,previous,next,date,locate);document.body.prepend(banner);
  function selectionQuery(){return '&series='+selection+(actual?'&symbol='+encodeURIComponent(actual):'');}
  async function load(offset){if(!cache||!alive)return;busy=true;
    const token=cache.begin(selection,actual);
    try{const response=await fetch('/bars?limit=2000'+(offset===undefined?'':'&offset='+Math.max(0,offset))+selectionQuery()+'&request_id='+token.request_id);
      if(!response.ok)throw Error();const page=await response.json();if(!alive||!cache.accept(page))return;
      payload={...header,...page,bars:cache.bars,symbol:selection==='signal'?header.config.continuous:actual};
      payload.contract_spec=header.contract_specs?.[actual]||header.contract_spec;
      layer?.dispose();layer=null;chart=null;requestKey='';install(true);if(header.account)emitAccount(header.account.time_ns||payload.as_of_ns);
      label.textContent=`离线复盘 · ${selection==='signal'?'因果拼接信号价（可能为负）':'实际合约原价'} · 已加载 ${page.offset+1}—${page.next_offset} / ${page.total_bars} 根 · 箭头详情为真实成交价 `;
    }catch(_){label.textContent='读取失败，请重新选择窗口；没有使用当前行情补造数据。';}
    finally{if(cache.request===Number(token.request_id))busy=false;}
  }
  function install(reset=false){if(!payload?.bars.length)return;
    const view=document.querySelector('.tq-top-view')?.__vue__,sdk=view?.$tqsdk;if(!sdk)return;
    const symbol=payload.symbol,duration=payload.bar_seconds*1e9,first=payload.bars[0].global_id,last=payload.bars.at(-1).global_id;
    const request=window.__replayRequests.web_chart||{chart_id:'web_chart',view_width:100};
    if(!reset&&layer&&requestKey===JSON.stringify(request)&&view.instrumentId===symbol&&view.duration===duration)return;
    const data={};for(const id of installed)data[id]=null;
    for(const b of payload.bars)data[b.global_id]={...b,datetime:Number(BigInt(b.time_ns))};
    installed=payload.bars.map(b=>b.global_id);
    const state={...request,ins_list:symbol,duration};
    sdk.dm.mergeData({subscribed:[{symbol,dur_nano:duration}],quotes:{[symbol]:{...payload.contract_spec,
      price_tick:Number(payload.contract_spec.price_tick),volume_multiple:Number(payload.contract_spec.volume_multiple),
      instrument_name:selection==='signal'?'主力连续信号价':'实际成交合约',ins_class:'FUTURE',last_price:Number(payload.bars.at(-1).close)}},
      charts:{web_chart:{state,more_data:false,left_id:first,right_id:last}},klines:{[symbol]:{[duration]:{data,last_id:last}}}});
    requestKey=JSON.stringify(request);view.instrumentId=symbol;view.duration=duration;
    const current=window.QfNativeHistory?.getChart?.();
    if(current?.symbol===symbol&&current.duration===duration){
      if(chart!==current||reset){layer?.dispose();chart=current;layer=QfNativeReplay.attach(chart,{onFill(f){
        if(parentOrigin)parent.postMessage({kind:'qf-replay-fill',run_id:header.run_id,revision:header.revision,fill:f},parentOrigin);
      },onTime:emitAccount});layer.apply(payload);if(reset)chart.setRange(Math.max(first,last-100),last);chart.draw();
        if(parentOrigin)parent.postMessage({kind:'qf-replay-ready',run_id:header.run_id,revision:header.revision},parentOrigin);}
    }
  }
  previous.onclick=()=>{if(payload&&!busy)load(payload.offset-2000);};
  next.onclick=()=>{if(payload&&!busy)load(Math.min(payload.total_bars-1,payload.next_offset));};
  series.onchange=()=>{selection=series.value==='signal'?'signal':'actual';actual=selection==='actual'?series.value:null;load();};
  async function focusTime(time){const token=cache.request,selected=selection;
    const response=await fetch('/locate?time_ns='+encodeURIComponent(time)+selectionQuery());
    if(response.ok&&token===cache.request&&selected===selection){const where=await response.json();await load(where.offset);return where.global_id;}}
  locate.onclick=()=>{if(date.value)focusTime(String(BigInt(Date.parse(date.value+'T00:00:00+08:00'))*1000000n));};
  fetch('/replay').then(r=>r.json()).then(value=>{header=value;cache=new WindowCache(header.run_id);
    series.add(new Option('主力连续信号图','signal'));for(const symbol of header.actual_symbols||[])series.add(new Option('实际合约 · '+symbol,symbol));load();
  }).catch(()=>{label.textContent='无法读取连续回测结果';});
  const timer=setInterval(()=>{if(!alive||busy||!payload)return;install();
    const range=chart?.chartCtrl?.range,first=payload.offset,last=payload.next_offset-1;
    if(range&&range.leftId<first&&first>0)load(Math.max(0,first-1500));
    else if(range&&range.rightId>last&&last<payload.total_bars-1)load(Math.min(payload.total_bars-2000,first+1500));
  },200);
  addEventListener('message',async e=>{if(!header||!QfNativeReplay.acceptMessage(e,parent,parentOrigin,header.run_id,header.revision))return;
    if(e.data.kind==='qf-replay-focus'){if(layer?.focusFill(e.data.fill_id))return;
      if(e.data.time_ns){await focusTime(e.data.time_ns);layer?.focusFill(e.data.fill_id);}}});
  addEventListener('pagehide',()=>{alive=false;clearInterval(timer);layer?.dispose();});
})();
