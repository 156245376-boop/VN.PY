// 仅由桌面宿主注入本机图表子页；不接入 Python 桥接，不改变合约值和点击事件。
(() => {
  if(window.__qfChartLabels)return;
  window.__qfChartLabels=true;
  let catalog=[],scheduled=false;
  const originals=new WeakMap();
  const observer=new MutationObserver(()=>{
    if(scheduled)return;scheduled=true;queueMicrotask(refresh);
  });
  function refresh(){
    scheduled=false;
    if(!document.body)return;
    observer.disconnect();
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const node=walker.currentNode,parent=node.parentElement;
      if(!parent||parent.closest('script,style,textarea,input,canvas'))continue;
      const previous=originals.get(node);
      const raw=previous?.rendered===node.nodeValue?previous.raw:node.nodeValue;
      const rendered=window.QfLabels.translate(raw,catalog);
      if(rendered!==node.nodeValue){node.nodeValue=rendered;parent.title=raw.trim()}
      originals.set(node,{raw,rendered});
    }
    observer.observe(document.body,{subtree:true,childList:true,characterData:true});
  }
  addEventListener('message',event=>{
    if(event.source!==parent||event.origin!==qfParentOrigin||event.data?.kind!=='qf-chart-labels')return;
    if(!Array.isArray(event.data.catalog))return;
    catalog=event.data.catalog.filter(row=>typeof row?.name==='string'&&typeof row?.product==='string'&&typeof row?.exchange==='string');
    refresh();
  });
  addEventListener('DOMContentLoaded',()=>{
    const style=document.createElement('style');
    style.textContent='.subscribed-list button{height:auto;min-height:26px;white-space:normal;line-height:1.5;padding:5px 7px}.subscribed-list button span{white-space:normal}';
    document.head.append(style);
    refresh();
    parent.postMessage({kind:'qf-chart-ready'},qfParentOrigin);
  });
})();
