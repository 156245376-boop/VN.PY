// 仅由桌面宿主注入本机图表子页；不接入 Python 桥接，通过原生按钮选择合约。
(() => {
  if(window.__qfChartLabels)return;
  window.__qfChartLabels=true;
  let catalog=[],scheduled=false,requestedSymbol='',pendingSymbol='',requestedPeriod='1m',revision=0;
  let paneId='',generation=0,compact=false,disposed=false,lastPeriod='';
  const periods={close:6e10,'1m':6e10,'5m':3e11,'15m':9e11,'30m':18e11,'1h':36e11,'1d':864e11};
  const emit=data=>parent.postMessage({...data,pane_id:paneId,generation,revision},qfParentOrigin);
  function configureView(){
    const view=document.querySelector('.tq-top-view')?.__vue__;
    if(!view)return;
    if(compact){
      document.documentElement.classList.add('qf-compact');
      view.rightClosed=true;view.rightClosedWidth=0;view.rightOpenedWidth=0;
      const home=document.querySelector('.tq-home')?.__vue__;
      if(home){home.topHeight=Math.max(260,innerHeight);home.bottomHeight=0;home.bottomYOffset=innerHeight;}
    }
    if(pendingSymbol){
      window.QfNativeTools?.cancelInteraction();
      view.instrumentId=requestedSymbol;view.duration=periods[requestedPeriod];
      view.mainType=requestedPeriod==='close'?'close':'candle';pendingSymbol='';
    }
  }
  const originals=new WeakMap();
  const observer=new MutationObserver(()=>{
    if(scheduled)return;scheduled=true;queueMicrotask(refresh);
  });
  function refresh(){
    scheduled=false;
    if(!document.body)return;
    observer.disconnect();
    try{
    const title=document.querySelector('.tq-top-view .title');
    const previousTitle=originals.get(title?.firstChild);
    const rawTitle=previousTitle&&previousTitle.rendered===title?.textContent?previousTitle.raw:title?.textContent||'';
    const symbol=rawTitle.trim().split(/\s+/)[0];
    const header=document.querySelector('.tq-header-view');
    if(header){let legend=document.querySelector('#qf-price-unit');
      if(!legend){legend=document.createElement('span');legend.id='qf-price-unit';header.append(legend)}
      legend.textContent='价格：'+window.QfLabels.quoteUnit(symbol,catalog)+' · 成交/持仓：手';}
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const node=walker.currentNode,parent=node.parentElement;
      if(!parent||parent.closest('script,style,textarea,input,canvas'))continue;
      const previous=originals.get(node);
      const raw=previous?.rendered===node.nodeValue?previous.raw:node.nodeValue;
      const button=parent.closest('.subscribed-list button');
      if(button){const parts=raw.trim().split(/\s+/);
        if(/^(?:KQ\.m@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}$/.test(parts[0])){
          button.dataset.qfSymbol=parts[0];button.dataset.qfPeriod=(parts[1]||'').toLowerCase();}}
      const rendered=parent.matches('.ivu-badge-status-text')&&raw.trim()==='行情'?
        raw.replace('行情','图表行情'):window.QfLabels.translate(raw,catalog);
      if(rendered!==node.nodeValue){node.nodeValue=rendered;parent.title=raw.trim()}
      originals.set(node,{raw,rendered});
    }
    configureView();
    }finally{observer.observe(document.body,{subtree:true,childList:true,characterData:true});}
  }
  addEventListener('message',event=>{
    if(event.source!==parent||event.origin!==qfParentOrigin)return;
    const data=event.data;
    if(data?.kind==='qf-chart-command'&&data.revision===revision&&
      (!paneId||(data.pane_id===paneId&&data.generation===generation))){
      const command=event.data.command;
      if(command==='dispose'){disposed=true;clearInterval(timer);observer.disconnect();window.QfNativeTools?.dispose();return}
      if(command==='cancel'){window.QfNativeTools?.cancelInteraction();return}
      const ok=command==='year'&&/^\d{4}$/.test(event.data.year||'')?
        window.QfNativeHistory?.jumpToYear(event.data.year):command==='latest'?
        window.QfNativeHistory?.navigateLatest():false;
      if(!ok)emit({kind:'qf-chart-command-failed'});
      return;
    }
    if(event.data?.kind!=='qf-chart-labels')return;
    if(disposed)return;
    if(paneId&&(data.pane_id!==paneId||data.generation<generation||
      data.generation===generation&&data.revision<revision))return;
    if(!Array.isArray(event.data.catalog))return;
    catalog=event.data.catalog.filter(row=>typeof row?.name==='string'&&typeof row?.product==='string'&&typeof row?.exchange==='string');
    revision=Number.isSafeInteger(event.data.revision)?event.data.revision:0;
    if(/^pane-[1-4]$/.test(data.pane_id||'')&&Number.isSafeInteger(data.generation)){
      paneId=data.pane_id;generation=data.generation;compact=data.compact===true;}
    const symbol=event.data.symbol;
    const period=Object.hasOwn(periods,event.data.period)?event.data.period:'1m';
    if(typeof symbol==='string'&&/^(?:KQ\.m@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}$/.test(symbol)&&
      (symbol!==requestedSymbol||period!==requestedPeriod)){
      requestedSymbol=symbol;pendingSymbol=symbol;requestedPeriod=period;lastPeriod=period;}
    refresh();
  });
  function reportHistory(){
    if(disposed||!requestedSymbol||!window.QfNativeHistory)return;
    try{const result=window.QfNativeHistory.inspect();
      configureView();
      const view=document.querySelector('.tq-top-view')?.__vue__;
      const period=view?.mainType==='close'?'close':Object.keys(periods).find(p=>p!=='close'&&periods[p]===view?.duration);
      if(view?.instrumentId===requestedSymbol&&period&&period!==lastPeriod){lastPeriod=period;emit({kind:'qf-chart-period',period});}
      emit({kind:'qf-chart-state',...result});
    }catch(_){emit({kind:'qf-chart-state',status:'unsupported'});}
  }
  addEventListener('DOMContentLoaded',()=>{
    const style=document.createElement('style');
    style.textContent=`
      .tq-top-view .left-view>.tq-layout-absolute:first-child{
        display:flex;align-items:center;gap:4px;width:100%!important;
        white-space:nowrap;overflow-x:auto;overflow-y:hidden;scrollbar-width:thin}
      .tq-top-view .left-view span.title{
        flex:0 1 260px;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .tq-button-group-durations,.tq-top-view .left-view .ivu-checkbox-wrapper{flex-shrink:0}
      .subscribed-list button{height:auto;min-height:26px;white-space:normal;line-height:1.5;padding:5px 7px}
      .subscribed-list button span{white-space:normal}
      #qf-price-unit{position:absolute;left:48px;top:25px;color:#657c70;font-size:10px;line-height:12px;pointer-events:none}`;
    style.textContent+=`.qf-compact .header-container,.qf-compact .tq-header-view,.qf-compact .bottom-container,.qf-compact .right-view{display:none!important}
      .qf-compact .top-container{top:0!important}.qf-compact #qf-price-unit{display:none}`;
    document.head.append(style);
    refresh();
    // 此事件仅表明标签脚本已加载；实际 K 线就绪另行核对。
    emit({kind:'qf-chart-ready'});
  });
  const timer=setInterval(reportHistory,400);
  addEventListener('resize',configureView);
  document.addEventListener('mousedown',()=>emit({kind:'qf-chart-activate'}),true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){
    const used=window.QfNativeTools?.cancelInteraction();event.preventDefault();event.stopImmediatePropagation();
    if(!used)emit({kind:'qf-chart-escape'});
  }},true);
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('.subscribed-list button');
    if(!button||!requestedSymbol||button.dataset.qfSymbol===requestedSymbol)return;
    const symbol=button.dataset.qfSymbol;
    const continuous=symbol?.replace(/^(?:KQ\.m@)?([A-Z]+\.[A-Za-z]+)\d*$/,'KQ.m@$1');
    if(catalog.some(row=>row.continuous===continuous)){
      event.preventDefault();event.stopImmediatePropagation();
      emit({kind:'qf-chart-selection',continuous,mode:symbol.startsWith('KQ.m@')?'continuous':'actual'});
    }
  },true);
})();
