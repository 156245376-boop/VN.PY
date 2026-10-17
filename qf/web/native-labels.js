// 仅由桌面宿主注入本机图表子页；不接入 Python 桥接，通过原生按钮选择合约。
(() => {
  if(window.__qfChartLabels)return;
  window.__qfChartLabels=true;
  let catalog=[],scheduled=false,requestedSymbol='',pendingSymbol='',requestedPeriod='1m',revision=0;
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
    if(pendingSymbol){const button=[...document.querySelectorAll('.subscribed-list button')]
      .find(item=>item.dataset.qfSymbol===pendingSymbol&&item.dataset.qfPeriod===requestedPeriod);
      if(button){pendingSymbol='';button.click();}}
    }finally{observer.observe(document.body,{subtree:true,childList:true,characterData:true});}
  }
  addEventListener('message',event=>{
    if(event.source!==parent||event.origin!==qfParentOrigin)return;
    if(event.data?.kind==='qf-chart-command'&&event.data.revision===revision){
      const command=event.data.command;
      const ok=command==='year'&&/^\d{4}$/.test(event.data.year||'')?
        window.QfNativeHistory?.jumpToYear(event.data.year):command==='latest'?
        window.QfNativeHistory?.navigateLatest():false;
      if(!ok)parent.postMessage({kind:'qf-chart-command-failed',revision},qfParentOrigin);
      return;
    }
    if(event.data?.kind!=='qf-chart-labels')return;
    if(!Array.isArray(event.data.catalog))return;
    catalog=event.data.catalog.filter(row=>typeof row?.name==='string'&&typeof row?.product==='string'&&typeof row?.exchange==='string');
    revision=Number.isSafeInteger(event.data.revision)?event.data.revision:0;
    const symbol=event.data.symbol;
    const period=event.data.period==='1d'?'1d':'1m';
    if(typeof symbol==='string'&&/^(?:KQ\.m@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}$/.test(symbol)&&
      (symbol!==requestedSymbol||period!==requestedPeriod)){
      requestedSymbol=symbol;pendingSymbol=symbol;requestedPeriod=period;}
    refresh();
  });
  function reportHistory(){
    if(!requestedSymbol||!window.QfNativeHistory)return;
    try{const result=window.QfNativeHistory.inspect();
      parent.postMessage({kind:'qf-chart-state',revision,...result},qfParentOrigin);
    }catch(_){parent.postMessage({kind:'qf-chart-state',revision,status:'unsupported'},qfParentOrigin);}
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
    document.head.append(style);
    refresh();
    // 此事件仅表明标签脚本已加载；实际 K 线就绪另行核对。
    parent.postMessage({kind:'qf-chart-ready'},qfParentOrigin);
  });
  setInterval(reportHistory,400);
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('.subscribed-list button');
    if(!button||!requestedSymbol||button.dataset.qfSymbol===requestedSymbol)return;
    const symbol=button.dataset.qfSymbol;
    const continuous=symbol?.replace(/^(?:KQ\.m@)?([A-Z]+\.[A-Za-z]+)\d*$/,'KQ.m@$1');
    if(catalog.some(row=>row.continuous===continuous)){
      event.preventDefault();event.stopImmediatePropagation();
      parent.postMessage({kind:'qf-chart-selection',revision,continuous,
        mode:symbol.startsWith('KQ.m@')?'continuous':'actual'},qfParentOrigin);
    }
  },true);
})();
