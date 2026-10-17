// 仅由桌面宿主注入本机图表子页；不接入 Python 桥接，通过原生按钮选择合约。
(() => {
  if(window.__qfChartLabels)return;
  window.__qfChartLabels=true;
  let catalog=[],scheduled=false,requestedSymbol='',pendingSymbol='';
  const originals=new WeakMap();
  const observer=new MutationObserver(()=>{
    if(scheduled)return;scheduled=true;queueMicrotask(refresh);
  });
  function refresh(){
    scheduled=false;
    if(!document.body)return;
    observer.disconnect();
    const title=document.querySelector('.tq-top-view .title');
    const rawTitle=originals.get(title?.firstChild)?.raw||title?.textContent||'';
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
        if(/^(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{3,4}$/.test(parts[0])){
          button.dataset.qfSymbol=parts[0];button.dataset.qfPeriod=parts[1]||'';}}
      const rendered=parent.matches('.ivu-badge-status-text')&&raw.trim()==='行情'?
        raw.replace('行情','图表行情'):window.QfLabels.translate(raw,catalog);
      if(rendered!==node.nodeValue){node.nodeValue=rendered;parent.title=raw.trim()}
      originals.set(node,{raw,rendered});
    }
    if(pendingSymbol){const button=[...document.querySelectorAll('.subscribed-list button')]
      .find(item=>item.dataset.qfSymbol===pendingSymbol&&item.dataset.qfPeriod==='1m');
      if(button){pendingSymbol='';button.click();}}
    observer.observe(document.body,{subtree:true,childList:true,characterData:true});
  }
  addEventListener('message',event=>{
    if(event.source!==parent||event.origin!==qfParentOrigin||event.data?.kind!=='qf-chart-labels')return;
    if(!Array.isArray(event.data.catalog))return;
    catalog=event.data.catalog.filter(row=>typeof row?.name==='string'&&typeof row?.product==='string'&&typeof row?.exchange==='string');
    const symbol=event.data.symbol;
    if(typeof symbol==='string'&&/^(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{3,4}$/.test(symbol)&&symbol!==requestedSymbol){
      requestedSymbol=symbol;pendingSymbol=symbol;}
    refresh();
  });
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
    parent.postMessage({kind:'qf-chart-ready'},qfParentOrigin);
  });
})();
