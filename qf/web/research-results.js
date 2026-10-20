(() => {
  'use strict';
  const number=value=>value===null||value===undefined||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:4});
  const precision=value=>value==='tick'?'Tick':value==='minute'?'分钟近似（流程验证）':'实时报价';
  const names={fast_period:'快均线（根）',slow_period:'慢均线（根）',symbol:'实际合约',continuous:'品种',bar_seconds:'K线周期（秒）',start:'起始交易日',end:'结束交易日',initial_balance:'初始资金（元）',precision:'数据精度',name:'实验名称',risk:'风险参数',
    strategy_version:'策略规则版本',schema_version:'配置版本',stop_method:'止损规则',pivot_left:'左侧确认柱',pivot_right:'右侧确认柱',limit_lots:'启用手数限制',limit_margin:'启用保证金限制',sizing:'定仓方式',fixed_lots:'固定手数',risk_budget:'风险预算（元）',stop_ticks:'初始止损（跳）',max_lots:'手数上限',max_margin_ratio:'保证金比例',take_profit_mode:'止盈方式',take_profit_value:'终点止盈',stairs_enabled:'阶梯保护',first_trigger_r:'第一档触发（R）',first_offset_ticks:'第一档偏移（跳）',second_trigger_r:'第二档触发（R）',second_lock_r:'第二档锁利（R）'};
  const fillName=f=>f.direction==='BUY'?(f.offset==='OPEN'?'买开（做多）':'买平（平空）'):(f.offset==='OPEN'?'卖开（做空）':'卖平（平多）');
  const reasonName=r=>({ma_reverse:'双均线反向交叉',initial_stop:'触发初始止损',stair_stop:'触发阶梯保护',take_profit:'达到终点止盈',user_flatten:'用户要求平仓停止'}[r]||'双均线交叉入场');
  const fillEvent=(events,key)=>events.find(e=>e.kind==='fill'&&e.payload?.fill_keys?.includes(key));
  const emptyFillText=count=>Number(count)>0?'当前窗口没有成交；全程有 '+number(count)+' 笔成交，可在复盘中按日期定位并点击箭头查看。':'本次没有实际成交；信号和目标不等于成交。';
  async function loadFillDetails(api,run,details,key){const fill=details.fills.find(f=>f.key===key);
    if(fill)return {fill,risk_events:details.risk_events};
    if(typeof api.get_research_fill!=='function')return null;
    const response=await api.get_research_fill(run,key);return response.ok?response.details:null;}
  function time(stamp){try{return new Date(Number(BigInt(stamp)/1000000n)+8*3600000).toISOString().slice(0,19).replace('T',' ');}catch(_){return '时间待核实';}}
  function create(root,api){let current=null,details={fills:[],risk_events:[]},binding=null,queued=null,disposed=false,fillRequest=0;
    const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text??'';return e;};
    const title=el('h3','实验结果与比较'),list=el('div'),compareButton=el('button','比较所选两个运行'),comparison=el('div'),summary=el('div'),reason=el('pre'),frame=document.createElement('iframe'),accountRoot=el('div');
    const selected=new Set(),tradeList=el('div');tradeList.className='table-scroll';reason.style.whiteSpace='pre-wrap';frame.hidden=true;accountRoot.hidden=true;
    const accountView=globalThis.QfAccountView?.create(accountRoot,{scenario:'research'});
    const replay=el('button','查看成交K线（离线复盘）');root.replaceChildren(title,list,compareButton,comparison,summary,replay,tradeList,reason,accountRoot,frame);
    function table(headers,rows){const t=el('table'),thead=el('thead'),head=el('tr'),body=el('tbody');for(const h of headers)head.append(el('th',h));thead.append(head);
      for(const row of rows){const tr=el('tr');for(const value of row)tr.append(el('td',value));body.append(tr);}t.append(thead,body);return t;}
    async function refresh(){const response=await api.list_research_runs();if(disposed)return;list.replaceChildren();
      for(const run of response.runs||[]){const label=el('label'),check=el('input');check.type='checkbox';check.checked=selected.has(run.run_id);check.disabled=!!run.issue;
        check.onchange=()=>{if(check.checked)selected.add(run.run_id);else selected.delete(run.run_id);};
        const button=el('button',run.issue||((run.config.name||'实验')+' · '+(run.fee_multiplier===2?'双倍费用':'基准费用')+' · '+precision(run.precision)));
        button.disabled=!!run.issue;button.title=run.run_id;button.onclick=async()=>{const r=await api.get_research_result(run.run_id);if(r.ok)render(r.result);else reason.textContent=r.reason;};label.append(check,button);list.append(label);}}
    function compare(payload){comparison.replaceChildren();const items=payload.items;
      comparison.append(table(['指标',...items.map(i=>i.config.name)],['net_pnl','commission','max_drawdown_amount','max_drawdown_pct','open_position'].map((key,i)=>[
        ['净收益（元）','费用（元）','最大回撤（元）','最大回撤（%）','期末净持仓（手）'][i],...items.map(r=>number(r[key]))])));
      for(const [key,pair]of Object.entries(payload.config_differences||{})){
        if(key==='risk'){for(const k of Object.keys(pair[0]))if(pair[0][k]!==pair[1][k])comparison.append(el('p',(names[k]||k)+'：'+pair[0][k]+' → '+pair[1][k]));}
        else comparison.append(el('p',(names[key]||key)+'：'+pair[0]+' → '+pair[1]));}
      if(payload.comparability_warnings?.length)comparison.append(el('p','注意：策略版本、止损规则、区间、资金、精度、费用或完成状态不同，请核对可比条件；成本压力回放不是参数A/B实验。'));}
    compareButton.onclick=async()=>{const r=await api.compare_research_runs([...selected]);if(r.ok)compare(r.comparison);else comparison.textContent=r.reason;};
    async function showFill(key,focus=true){const run=current?.run_id,request=++fillRequest;let packet;
      try{packet=await loadFillDetails(api,run,details,key);}catch(_){packet=null;}
      if(disposed||current?.run_id!==run||request!==fillRequest)return;
      if(!packet){reason.textContent='未能读取该成交的已保存证据。';return;}
      const f=packet.fill;
      const events=packet.risk_events.filter(e=>BigInt(e.time_ns)<=BigInt(f.time_ns)),last=fillEvent(packet.risk_events,f.key),signal=events.findLast(e=>e.payload?.signal)?.payload.signal;
      let trade=null;try{const response=await api.get_research_trade?.(run,key);if(response?.ok)trade=response.details;}catch(_){}
      const r=last?.risk||{};reason.textContent=fillName(f)+' · '+time(f.time_ns)+'（北京时间）\n成交：'+number(f.volume)+' 手，价格 '+number(f.price)+'\n原因：'+reasonName(r.exit_reason)+
        '\n初始R：'+number(trade?.initial_r??r.initial_r)+' 元；阶梯：'+(r.stage??'—')+'；保护价：'+number(trade?.entry_plan?.stop_price??r.stop_price)+(signal?'\n交叉依据：快线 '+number(signal.fast_current)+'；慢线 '+number(signal.slow_current):'')+(trade?.pivot?'\n确认拐点：'+trade.pivot.kind+' '+number(trade.pivot.price)+' · 确认时间 '+time(trade.pivot.confirmed_ns):'');
      if(binding&&focus)frame.contentWindow.postMessage({kind:'qf-replay-focus',run_id:binding.run_id,revision:binding.revision,fill_id:key,time_ns:f.time_ns},new URL(binding.url).origin);}
    async function openReplay(){if(!current)return;const r=await api.open_research_replay(current.run_id);if(!r.ok){reason.textContent=r.reason;return;}
      binding=r;frame.hidden=false;frame.src=r.url;}
    replay.onclick=openReplay;
    async function render(result){current=result;details={fills:[],risk_events:[]};summary.replaceChildren();
      summary.append(el('h3',result.config.name+' · '+(result.fee_multiplier===2?'双倍费用压力回放':'基准费用')+' · '+precision(result.precision)));
      summary.append(table(['净收益（元）','毛收益（元）','手续费（元）','最大回撤（元）','完整交易次数','期末净持仓（手）'],[[number(result.net_pnl),number(result.gross_pnl),number(result.commission),number(result.max_drawdown_amount),number(result.closed_trade_count),number(result.open_position)]]));
      if(result.status!=='backtest_finished')summary.append(el('p','本次为模拟、已停止或未完成运行，请核实状态；不得当作完整回测结果。'));
      summary.append(el('p','毛盈利不含手续费；期末持仓没有自动平仓，净收益包含市值变动。SDK成本不代表历史真实交易成本。'));
      if(result.config.schema_version===3)summary.append(el('p',`历史主力连续 · 换月 ${result.roll_count??0} 次 · 移仓手续费 ${number(result.roll_commission)} 元（已包含在总手续费） · 完整交易按逻辑交易统计；信号图使用因果拼接价格，成交详情保留实际合约原价。`));
      if(binding?.run_id!==result.run_id){frame.hidden=true;frame.removeAttribute('src');binding=null;}
      const r=await api.get_research_result(result.run_id);if(disposed||current.run_id!==result.run_id)return;if(!r.ok){reason.textContent=r.reason;return;}
      details=r.details;tradeList.replaceChildren();accountRoot.hidden=!details.account;if(accountView)accountView.update(details.account,[]);
      const t=table(['成交时间（北京时间）','操作','手数','成交价','原因'],[]);const body=t.querySelector('tbody');
      for(const f of details.fills){const tr=el('tr');for(const text of [time(f.time_ns),fillName(f)+(f.symbol?' · '+f.symbol:'')+(f.role==='roll_out'?'（移仓平旧）':f.role==='roll_in'?'（移仓开新）':''),number(f.volume),number(f.price),'点击查看并定位'])tr.append(el('td',text));
        tr.style.cursor='pointer';tr.onclick=async()=>{showFill(f.key);if(!binding){queued=f.key;await openReplay();}};body.append(tr);}tradeList.append(t);
      if(!details.fills.length)tradeList.append(el('p',emptyFillText(result.fill_count)));}
    function message(e){if(!binding||e.source!==frame.contentWindow||e.origin!==new URL(binding.url).origin||e.data?.run_id!==binding.run_id||e.data?.revision!==binding.revision)return;
      if(e.data.kind==='qf-replay-ready'&&queued){const key=queued;queued=null;showFill(key);}
      if(e.data.kind==='qf-research-account'&&e.data.account){accountRoot.hidden=false;accountView?.update(e.data.account,[]);}
      if(e.data.kind==='qf-replay-fill')showFill(e.data.fill?.key,false);}
    addEventListener('message',message);refresh().catch(()=>{});
    return {refresh,render,compare,dispose(){disposed=true;removeEventListener('message',message);frame.removeAttribute('src');accountView?.dispose?.();}};
  }
  globalThis.QfResearchResults={create,number,precision,fillName,fillEvent,loadFillDetails,emptyFillText};
})();
