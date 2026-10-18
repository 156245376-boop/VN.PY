// 父页指标协调：窗口身份、版本、节流、纯计算和独立保存。
(() => {
  'use strict';const clone=v=>JSON.parse(JSON.stringify(v));
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const mathKey=items=>JSON.stringify(items.map(({id,type,visible,params})=>({id,type,visible,params})));
  function create(options){let config=clone(options.config),alive=true,polling=false,saving=null,pendingSave=null;
    const panes=new Map(Object.entries(config.panes).map(([id,p])=>[id,{settings:clone(p),revision:1,visible:true,token:'',sent:'',job:null,timer:null,lastSubmit:0}]));
    function identity(id){const p=options.getPane(id);return p?.identity?{...p.identity,settings_revision:panes.get(id).revision}:null;}
    function send(id,data){options.getPane(id)?.send(data);}
    function sync(){if(!alive)return;for(const [id,s]of panes){const p=identity(id),key=JSON.stringify([p,s.settings,s.visible]);
      if(!p||key===s.sent)continue;s.sent=key;
      send(id,{kind:'qf-indicator-config',...p,settings:s.settings,enabled:s.visible});}}
    async function save(){pendingSave=clone(config);if(saving)return saving;
      saving=(async()=>{while(pendingSave&&alive){const c=pendingSave;pendingSave=null;const r=await options.save(c);if(!r.ok)options.onNotice?.(r.reason);}})();
      try{await saving;}finally{saving=null;}}
    function configure(id,settings){const s=panes.get(id);if(!s)return;
      if(mathKey(s.settings.items)!==mathKey(settings.items)){s.revision++;s.token='';s.job=null;}
      s.settings=clone(settings);config.panes[id]=clone(settings);s.sent='';sync();save().catch(()=>options.onNotice?.('指标设置未保存。'));}
    function valid(id,d){const i=identity(id);return i&&Object.entries(i).every(([k,v])=>d[k]===v);}
    function clear(id,reason){send(id,{kind:'qf-indicator-result',...identity(id),result:{series:[],profiles:[],issues:[{item_id:'all',reason}]}});}
    function onMessage(event){const d=event.data,id=d?.pane_id,s=panes.get(id),p=options.getPane(id);
      if(!alive||!s?.visible||!p||event.source!==p.source||event.origin!==p.origin||!valid(id,d))return;
      if(['qf-vp-range-change','qf-indicator-height'].includes(d.kind)){options.onRange?.(id,d);return;}
      if(d.kind!=='qf-indicator-data')return;
      if(d.issue){s.job=null;s.token='';clear(id,d.issue);return;}
      if(d.data_revision===s.token)return;s.token=d.data_revision;clearTimeout(s.timer);
      const request={};for(const key of ['pane_id','generation','chart_revision','settings_revision','symbol','period','data_revision','request_id','rows','visible','price_tick','coverage_end_ns'])request[key]=d[key];
      request.items=clone(s.settings.items);
      s.timer=setTimeout(async()=>{s.timer=null;if(!alive||!s.visible||!valid(id,d)||s.token!==d.data_revision)return;
        s.lastSubmit=Date.now();try{const result=await options.submit(request);
          if(!alive||!valid(id,d)||s.token!==d.data_revision)return;
          if(result.ok)s.job={id:result.job_id,data_revision:d.data_revision,request_id:d.request_id};else clear(id,result.reason);
        }catch(_){clear(id,'指标计算暂不可用。');}
      },Math.max(options.delay??250,500-(Date.now()-s.lastSubmit)));}
    async function poll(){if(!alive||polling)return;const ids=[...panes.values()].map(s=>s.job?.id).filter(Boolean);if(!ids.length)return;
      polling=true;try{const results=await options.poll(ids);if(!alive)return;
        for(const [id,s]of panes){const job=s.job,r=job&&results[job.id];if(!r||['queued','running'].includes(r.status))continue;s.job=null;
          if(!s.visible||!r.identity||!valid(id,r.identity)||r.identity.data_revision!==s.token||r.identity.request_id!==job.request_id)continue;
          if(r.status==='ready'){send(id,{kind:'qf-indicator-result',...r.identity,result:r.result});options.onResult?.(id,r.result);}
          else clear(id,r.reason||'指标计算已被更新请求替代。');}
      }catch(_){}finally{polling=false;}}
    const timer=setInterval(poll,200);
    return {configure,sync,onMessage,poll,getConfig:()=>clone(config),setVisible(id,value){const s=panes.get(id);if(!s||s.visible===value)return;s.visible=value;s.sent='';s.job=null;s.token='';clearTimeout(s.timer);sync();},
      command(id,command,item_id){if(['begin','locate','cancel'].includes(command))send(id,{kind:'qf-vp-range-command',...identity(id),command,item_id});},
      async flush(){await save();},dispose(){alive=false;clearInterval(timer);for(const s of panes.values())clearTimeout(s.timer);pendingSave=null;},
      invalidate(id){const s=panes.get(id);if(s){s.sent='';s.token='';s.job=null;clearTimeout(s.timer);sync();}}};
  }
  window.QfIndicatorController={create};
})();
