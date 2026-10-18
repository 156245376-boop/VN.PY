(() => {
  'use strict';
  function create(root,options={}){
    root.className='account-view';root.innerHTML=`<details open><summary>本地模拟账户 · 行情窗口</summary>
      <p class="account-state"></p><div class="account-metrics"></div>
      <div class="account-tabs"><button data-tab="positions">持仓</button><button data-tab="orders">委托记录</button><button data-tab="trades">成交记录</button></div>
      <div class="table-scroll"><table><thead></thead><tbody></tbody></table><p class="account-empty"></p></div></details>`;
    const details=root.querySelector('details');let snapshot=null,tab='positions',catalog=[];
    details.addEventListener('toggle',()=>options.onCollapse?.(!details.open));
    root.querySelector('summary').onclick=event=>{event.preventDefault();
      if(options.onCollapse)options.onCollapse(details.open);else details.open=!details.open;};
    const columns={positions:[['symbol','合约'],['pos_long','多头（手）'],['pos_short','空头（手）'],['float_profit','浮动盈亏（元）'],['margin','保证金（元）']],
      orders:[['symbol','合约'],['direction','方向'],['offset','开平'],['volume_orign','原始手数'],['volume_left','剩余手数'],['limit_price','委托价'],['status','状态']],
      trades:[['symbol','合约'],['direction','方向'],['offset','开平'],['volume','成交手数'],['price','成交价'],['trade_date_time','成交时间（北京时间）']]};
    const terms={BUY:'买',SELL:'卖',OPEN:'开仓',CLOSE:'平仓',CLOSETODAY:'平今',ALIVE:'未结束',FINISHED:'已结束（不等于全部成交）'};
    const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
    const value=x=>x==null?'—':typeof x==='number'?x.toLocaleString('zh-CN',{maximumFractionDigits:3}):terms[x]||x;
    function render(){
      root.querySelector('.account-state').textContent=snapshot?
        (snapshot.connected?'末次本机读取：':'连接中断或数据待核实，末次快照：')+(snapshot.observed_at||'待确认')+' · 此处权益为本地虚拟资金，不是快期模拟账户余额。':'等待读取本地模拟账户；此处不是快期模拟账户余额。';
      const metrics=root.querySelector('.account-metrics');metrics.replaceChildren();
      for(const [key,name] of [['balance','账户权益'],['float_profit','浮动盈亏'],['margin','保证金占用'],['commission','手续费'],['available','可用资金']])
        metrics.append(text('span',name+'：'+value(snapshot?.summary?.[key])+' 元'));
      const head=root.querySelector('thead'),body=root.querySelector('tbody'),tr=document.createElement('tr');head.replaceChildren(tr);body.replaceChildren();
      for(const [,label] of columns[tab])tr.append(text('th',label));
      for(const item of snapshot?.[tab]||[]){const row=document.createElement('tr');
        for(const [key] of columns[tab]){let v=item[key];if(key==='symbol')v=QfLabels.contractName(v,catalog);
          if(['limit_price','price'].includes(key)&&v!=null)v=value(v)+' '+QfLabels.quoteUnit(item.symbol,catalog);
          if(key==='trade_date_time'&&Number.isFinite(v)){
          const date=new Date(v/1e6+8*3600e3);v=Number.isFinite(date.getTime())?date.toISOString().slice(0,19).replace('T',' '):null;}
          row.append(text('td',value(v)));}body.append(row);}
      root.querySelector('.account-empty').textContent=snapshot?.[tab]?.length?
        (snapshot.truncated?.[tab]?'仅显示最近 500 条账户记录。':''):({positions:'暂无持仓',orders:'暂无委托记录',trades:'暂无成交记录'})[tab];
      for(const b of root.querySelectorAll('[data-tab]'))b.classList.toggle('selected',b.dataset.tab===tab);
    }
    for(const b of root.querySelectorAll('[data-tab]'))b.onclick=()=>{tab=b.dataset.tab;render();};
    render();return {update(value,products=[]){snapshot=value;catalog=products;render();},setCollapsed(value){details.open=!value;}};
  }
  window.QfAccountView={create};
})();
