(() => {
  'use strict';
  const researchMetrics=[['balance','账户权益'],['float_profit','浮动盈亏'],['margin','保证金占用'],['available','可用资金'],['commission','日内手续费'],['commission_total','累计手续费'],['roll_commission','移仓手续费'],['actual_fill_count','实际成交'],['closed_trade_count','完整交易'],['open_position','未结束持仓']];
  const marketMetrics=[['balance','账户权益'],['float_profit','浮动盈亏'],['margin','保证金占用'],['commission','手续费'],['available','可用资金']];
  const terms={BUY:'买',SELL:'卖',OPEN:'开仓',CLOSE:'平仓',CLOSETODAY:'平今',
    ALIVE:'未结束',FINISHED:'已结束',open:'持仓中',closed:'已平仓',
    strategy_open:'策略开仓',strategy_close:'策略平仓',roll_out:'移仓平旧',roll_in:'移仓开新',
    initial_stop:'初始止损',stair_stop:'阶梯保护',take_profit:'终点止盈',
    ma_reverse:'反向交叉',user_flatten:'用户平仓停止',entry_stop_invalid:'入场即越过止损'};
  const reasonNames={ma_reverse:'反向交叉',initial_stop:'初始止损',stair_stop:'阶梯保护',
    take_profit:'终点止盈',user_flatten:'用户要求平仓',entry_stop_invalid:'入场即越过止损',
    strategy_close:'策略平仓'};
  const ledgerColumns=[['status','状态'],['first_symbol','开仓合约'],['last_symbol','平仓合约'],
    ['direction','方向'],['quantity','手数'],['entry_time_ns','开仓时间'],
    ['entry_price','开仓均价'],['exit_time_ns','平仓时间'],['exit_price','平仓均价'],
    ['initial_stop','初始止损'],['final_stop','最终保护'],['fee','手续费（元）'],
    ['gross_pnl','毛盈亏（元）'],['net_pnl','净盈亏（元）'],['exit_reason','退出原因']];
  const ledgerFillColumns=[['time_ns','成交时间'],['symbol','合约'],['direction','方向'],
    ['offset','开平'],['role','用途'],['volume','手数'],['price','成交价'],['fee','本笔手续费（元）'],
    ['trade_status','交易状态'],['entry_price','开仓均价'],['exit_price','平仓均价'],
    ['initial_stop','初始止损'],['final_stop','最终保护'],
    ['trade_net_pnl','所属交易净盈亏（元）'],['exit_reason','退出原因']];
  const snapshotTradeColumns=[['symbol','合约'],['direction','方向'],['offset','开平'],
    ['volume','成交手数'],['price','成交价'],['trade_date_time','成交时间（北京时间）']];
  const columns={positions:[['symbol','合约'],['pos_long','多头（手）'],['pos_short','空头（手）'],
    ['float_profit','浮动盈亏（元）'],['margin','保证金（元）']],
    orders:[['symbol','合约'],['direction','方向'],['offset','开平'],['volume_orign','原始手数'],
      ['volume_left','剩余手数'],['limit_price','委托价'],['status','状态']]};

  function stateText(snapshot,scenario){
    if(!snapshot)return scenario==='research'?'等待本次回测账户快照。':'等待读取本地模拟账户；此处不是快期模拟账户余额。';
    if(scenario==='research')return snapshot.status==='last_snapshot'?'本次回测已停止或完成 · 显示末次账户快照 '+(snapshot.time_ns||'时间未记录'):'本次回测账户 · 回测时间 '+(snapshot.time_ns||'待核实');
    return (snapshot.connected?'末次本机读取：':'连接中断或数据待核实，末次快照：')+(snapshot.observed_at||'待确认')+' · 此处权益为本地虚拟资金，不是快期模拟账户余额。';
  }
  function metricRows(snapshot,scenario='market'){
    const summary=snapshot?.summary||{},rows=[];
    for(const [key,name] of scenario==='research'?researchMetrics:marketMetrics){
      let value=summary[key];if(value===undefined||value===null)value=scenario==='research'?'未记录':null;
      const unit=key==='actual_fill_count'||key==='closed_trade_count'?'笔':key==='open_position'?'手':'元';
      rows.push([name,value,unit]);
    }
    return rows;
  }
  function timeText(stamp){
    if(stamp==null||stamp==='')return '—';
    try{return new Date(Number(BigInt(stamp)/1000000n)+8*3600000).toISOString()
      .slice(0,19).replace('T',' ');}catch(_){return '待核实';}
  }
  function create(root,options={}){
    const scenario=options.scenario==='research'?'research':'market';
    root.className='account-view';
    root.innerHTML=`<details open><summary>${scenario==='research'?'本次回测账户':'本地模拟账户 · 行情窗口'}</summary>
      <p class="account-state"></p><div class="account-metrics"></div>
      <div class="account-tabs"><button data-tab="positions">持仓</button><button data-tab="orders">委托记录</button><button data-tab="trades">成交记录</button><button data-tab="ledger">交易明细</button></div>
      <p class="account-ledger-warning" hidden></p>
      <div class="table-scroll"><table><thead></thead><tbody></tbody></table><p class="account-empty"></p></div></details>`;
    const details=root.querySelector('details'),state=root.querySelector('.account-state'),
      metrics=root.querySelector('.account-metrics'),warning=root.querySelector('.account-ledger-warning'),
      tableScroll=root.querySelector('.table-scroll'),head=root.querySelector('thead'),
      body=root.querySelector('tbody'),empty=root.querySelector('.account-empty');
    let snapshot=null,ledger=null,catalog=[],tab='positions',headerMode='',
      summaryKey='',tableKey='',metricNodes=new Map(),rowNodes=new Map();
    const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
    const value=x=>x==null?'—':typeof x==='number'?x.toLocaleString('zh-CN',{maximumFractionDigits:3}):terms[x]||reasonNames[x]||x;
    const display=x=>x==null?'—':typeof x==='number'||(typeof x==='string'&&x.trim()!==''&&Number.isFinite(Number(x)))?Number(x).toLocaleString('zh-CN',{maximumFractionDigits:3}):value(x);
    const currentColumns=()=>tab==='ledger'?ledgerColumns:tab==='trades'
      ?(ledger?.available&&ledger.fills?.length?ledgerFillColumns:snapshotTradeColumns):columns[tab];
    const currentRows=()=>tab==='ledger'?(ledger?.trades||[]):tab==='trades'
      ?(ledger?.available&&ledger.fills?.length?ledger.fills:(snapshot?.trades||[])):
      (snapshot?.[tab]||[]);
    function format(key,item){
      let v=item[key];
      if(key==='symbol'||key==='first_symbol'||key==='last_symbol')v=QfLabels.contractName(v,catalog);
      else if(['limit_price','price','entry_price','exit_price','initial_stop','final_stop'].includes(key)&&v!=null)
        v=display(v)+' '+QfLabels.quoteUnit(item.symbol||item.first_symbol||item.last_symbol,catalog);
      else if(['time_ns','entry_time_ns','exit_time_ns'].includes(key))v=v==null?'—':timeText(v);
      else if(key==='trade_date_time')v=v==null?'—':timeText(v);
      else if(key==='direction')v=item.direction_text||(v===1?'多':v===-1?'空':v);
      else v=display(v);
      return v;
    }
    function rowKey(item,index){
      if(tab==='ledger')return 'trade:'+item.trade_id;
      if(tab==='trades'&&ledger?.available&&ledger.fills?.length)return 'fill:'+item.key;
      return [tab,item.symbol||'',item.direction||'',item.offset||'',
        item.trade_date_time||item.limit_price||'',index].join('|');
    }
    function renderSummary(){
      const next=stateText(snapshot,scenario);if(state.textContent!==next)state.textContent=next;
      const rows=metricRows(snapshot,scenario),key=JSON.stringify([rows,scenario]);
      if(key===summaryKey)return;
      summaryKey=key;
      for(const [name,item,unit] of rows){
        let node=metricNodes.get(name);
        if(!node){node=text('span','');metricNodes.set(name,node);metrics.append(node);}
        const nextText=name+'：'+display(item)+(item==='未记录'?'':' '+unit);
        if(node.textContent!==nextText)node.textContent=nextText;
      }
    }
    function renderTable(){
      const rows=currentRows(),cols=currentColumns(),mode=tab+':'+cols.map(c=>c[0]).join(',');
      const nextKey=JSON.stringify([mode,catalog.map(x=>x.continuous+':'+x.name),rows]);
      if(nextKey===tableKey)return;
      tableKey=nextKey;const scroll=tableScroll.scrollTop;
      if(mode!==headerMode){
        headerMode=mode;const tr=document.createElement('tr');
        for(const [,label] of cols)tr.append(text('th',label));
        head.replaceChildren(tr);rowNodes.clear();body.replaceChildren();
      }
      const seen=new Set();
      rows.forEach((item,index)=>{
        const key=rowKey(item,index);seen.add(key);
        let row=rowNodes.get(key);
        if(!row){row=document.createElement('tr');row.__cells=[];rowNodes.set(key,row);}
        const cells=row.__cells;
        while(cells.length<cols.length){const cell=document.createElement('td');cells.push(cell);row.append(cell);}
        while(cells.length>cols.length)cells.pop().remove();
        cols.forEach(([field],cellIndex)=>{
          const next=format(field,item);if(cells[cellIndex].textContent!==next)cells[cellIndex].textContent=next;
        });
        if(row.dataset.tradeId!==String(item.trade_id||''))row.dataset.tradeId=String(item.trade_id||'');
        body.append(row);
      });
      for(const [key,row] of rowNodes){
        if(!seen.has(key)){row.remove();rowNodes.delete(key);}
      }
      tableScroll.scrollTop=scroll;
      const unavailable=tab!=='ledger'&&scenario==='research'
        &&snapshot?.availability?.[tab]!=='recorded';
      const names={positions:'持仓',orders:'委托',trades:'成交',ledger:'交易明细'};
      empty.textContent=tab==='ledger'&&!ledger?'正在读取本次交易的完整证据。':
        unavailable?'该历史时点未保存'+names[tab]+'明细。':rows.length?
        (snapshot?.truncated?.[tab]?'仅显示最近 500 条账户记录。':''):
        ({positions:'暂无持仓',orders:'暂无委托记录',trades:'暂无成交记录',ledger:'暂无完整交易'})[tab];
      for(const button of root.querySelectorAll('[data-tab]'))
        button.classList.toggle('selected',button.dataset.tab===tab);
    }
    function render(){
      renderSummary();renderTable();
      const visibleLedger=tab==='ledger'||(tab==='trades'&&ledger?.available);
      warning.hidden=!visibleLedger||!ledger;
      warning.textContent=visibleLedger&&ledger&&!ledger.available
        ?(ledger.reason||'逐笔交易账本不可用。'):
        visibleLedger&&ledger&&!ledger.reconciled
          ?'账本费用与成交费用合计未完全核对，请查看原始记录。':'';
    }
    details.addEventListener('toggle',()=>options.onCollapse?.(!details.open));
    root.querySelector('summary').onclick=event=>{event.preventDefault();
      if(options.onCollapse)options.onCollapse(details.open);else details.open=!details.open;};
    for(const button of root.querySelectorAll('[data-tab]'))
      button.onclick=()=>{tab=button.dataset.tab;render();};
    render();
    return {
      update(next,products=[],nextLedger=null){
        snapshot=next||null;catalog=products||[];ledger=nextLedger||null;render();
      },
      setCollapsed(value){details.open=!value;},
      inspect(){return {tab,rowCount:body.children.length,rowNodes:rowNodes.size,tableKey};}
    };
  }
  window.QfAccountView={create,metricRows,stateText};
  globalThis.QfAccountView=window.QfAccountView;
})();
