// 运行视图只接收已处理前缀；图表绑定代号与快照序号分别核对。
(() => {
  'use strict';
  const acceptMessage=(e,source,origin,run,generation)=>e.source===source&&e.origin===origin&&e.data?.run_id===run&&e.data?.generation===generation;
  function attach(chart,options){let revision=0,alive=true;const layer=options.layer||QfNativeReplay.attach(chart,options);
    return {apply(snapshot){if(!alive||snapshot.run_id!==options.run_id||!Number.isSafeInteger(snapshot.revision)||snapshot.revision<=revision)return false;
      const now=BigInt(snapshot.as_of_ns);
      if((snapshot.bars||[]).some(b=>BigInt(b.time_ns)>now||b.completed&&BigInt(b.end_ns)>now)||
        (snapshot.fills||[]).some(f=>BigInt(f.time_ns)>now)||(snapshot.risk_events||[]).some(e=>BigInt(e.time_ns)>now)||
        (snapshot.ma_series||[]).some(s=>s.points.some(p=>BigInt(p.time_ns)>now)))return false;
      options.install?.(snapshot);const accepted=layer.apply({...snapshot,revision:options.generation});
      if(accepted)revision=snapshot.revision;return accepted;
    },dispose(){alive=false;layer.dispose();}};
  }
  globalThis.QfNativeLiveResearch={attach,acceptMessage};
  if(typeof window==='undefined'||!window.__qfLiveResearch)return;
  const binding=window.__qfLiveResearch;let run=binding.run_id,revision=0,payload=null,layer=null,chart=null,busy=false,alive=true,paused=false,installed=0,lastRequest='';
  let parentOrigin=null;try{parentOrigin=new URL(document.referrer).origin;}catch(_){}
  const banner=document.createElement('div');banner.className='qf-replay-banner';banner.textContent='运行图 · 等待后台处理历史数据；不会另行连接账户';document.body.prepend(banner);
  const emit=kind=>{if(parentOrigin)parent.postMessage({kind,run_id:run,generation:binding.generation,revision},parentOrigin);};
  function install(next){const view=document.querySelector('.tq-top-view')?.__vue__,sdk=view?.$tqsdk;if(!sdk)return;
    const first=next.first_bar_id||0,last=first+next.bars.length-1,duration=next.bar_seconds*1e9,symbol=next.symbol;
    const request=window.__replayRequests.web_chart||{chart_id:'web_chart',ins_list:symbol,duration,view_width:100};
    const data={};for(const [i,row] of next.bars.entries())data[first+i]={...row,datetime:Number(BigInt(row.time_ns))};
    const existing=sdk.get_by_path(['klines',symbol,duration])?.data||{};
    for(const id of Object.keys(existing))if(Number(id)<first)data[id]=null;
    const old=chart?.chartCtrl,follow=!old||old.range.rightId>=installed-2;
    const state={...request,ins_list:symbol,duration};
    const diff={quotes:{[symbol]:{...next.quote,ins_class:'FUTURE',price_tick:Number(next.contract_spec.price_tick),volume_multiple:Number(next.contract_spec.volume_multiple)}},
      subscribed:[{symbol,dur_nano:duration}],charts:{web_chart:{state,more_data:false,left_id:first,right_id:last}},
      klines:{[symbol]:{[duration]:{data,last_id:last}}}};
    sdk.dm.mergeData(diff);installed=last;
    if(follow&&chart)chart.setRange(Math.max(first,last-100),last);
    lastRequest=JSON.stringify(request);
  }
  function draw(){if(!payload?.bars?.length)return false;const view=document.querySelector('.tq-top-view')?.__vue__,sdk=view?.$tqsdk;if(!sdk)return false;
    const duration=payload.bar_seconds*1e9;
    if(view.instrumentId!==payload.symbol||view.duration!==duration){install(payload);view.instrumentId=payload.symbol;view.duration=duration;return false;}
    const next=window.QfNativeHistory?.getChart?.();if(!next||next.symbol!==payload.symbol||next.duration!==duration){install(payload);return false;}
    if(next!==chart){layer?.dispose();chart=next;layer=attach(chart,{run_id:run,generation:binding.generation,install});}
    const applied=layer.apply(payload);if(applied)emit('qf-live-ready');
    const request=window.__replayRequests.web_chart;
    if(request&&JSON.stringify(request)!==lastRequest)install(payload);
    return applied;
  }
  async function poll(){if(busy||!alive||paused||document.hidden)return;busy=true;
    try{const response=await fetch('/snapshot?after_revision='+revision,{cache:'no-store'});if(!response.ok)throw Error();const packet=await response.json();
      if(packet.generation!==binding.generation||run&&packet.run_id!==run)return;
      if(packet.changed){run=packet.run_id;payload=packet.snapshot;revision=payload.revision;
        banner.textContent=`运行过程（${payload.terminal?(payload.progress.finished?'已保存完成':'未完成／已停止'):'计算中'}） · 只显示最近500根K线、窗口内最多5000条事件 · 图表时间 ${new Date(Number(BigInt(payload.as_of_ns)/1000000n)).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · 全部证据保存在本机结果中`;}
      draw();
    }catch(_){banner.textContent='运行图暂时读取失败；后台继续计算，请查看主页面进度。';}
    finally{busy=false;}
  }
  const timer=setInterval(poll,250);poll();
  addEventListener('message',e=>{if(!acceptMessage(e,parent,parentOrigin,run,binding.generation))return;
    if(e.data.kind==='qf-live-pause')paused=!!e.data.paused;
    if(!paused)poll();});
  addEventListener('pagehide',()=>{alive=false;clearInterval(timer);layer?.dispose();});
})();
