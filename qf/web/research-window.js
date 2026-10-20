(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const statusNames={waiting:'等待空闲',starting:'正在启动',active:'运行中',warmup:'预热中',
    backtesting:'回测中',stopping:'停止中',saving:'保存中',backtest_finished:'回测完成',
    stopped:'已停止',failed:'失败',frozen:'已冻结',interrupted:'异常中断'};
  const reasonNames={capacity:'等待并发槽位',historical_replay_completed:'历史回放完成',
    requested_stop:'用户要求停止',connection_lost:'连接中断',
    sdk_or_auth_or_permission_error:'认证、权限或SDK请求失败'};
  const filters=[...document.querySelectorAll('[data-ledger-filter]')];
  let accountView=null,ledgerPacket=null,lastLedgerKey='',filterTimer=null,stateData=null,chartUrl='';
  const number=(value,digits=2)=>value==null||value===''?'—':Number(value).toLocaleString(
    'zh-CN',{maximumFractionDigits:digits});
  const text=(id,value)=>{const node=$(id);if(node&&node.textContent!==value)node.textContent=value;};
  function filterQuery(){
    const params=new URLSearchParams();
    for(const field of filters){if(field.value.trim())params.set(field.dataset.ledgerFilter,field.value.trim());}
    return params.toString();
  }
  function renderStats(stats){
    const items=[['交易数',stats?.count??0,'笔'],['完整交易',stats?.closed_count??0,'笔'],
      ['持仓中',stats?.open_count??0,'笔'],['胜率',number(stats?.win_rate,2),'%'],
      ['盈利笔数',stats?.wins??0,'笔'],['亏损笔数',stats?.losses??0,'笔'],
      ['毛盈亏',number(stats?.gross_pnl),'元'],['手续费',number(stats?.fee),'元'],
      ['净盈亏',number(stats?.net_pnl),'元'],['平均盈利',number(stats?.average_win),'元'],
      ['平均亏损',number(stats?.average_loss),'元'],['最大单笔盈利',number(stats?.max_win),'元'],
      ['最大单笔亏损',number(stats?.max_loss),'元']];
    const root=$('ledger-stats');root.replaceChildren();
    for(const [name,value,unit] of items){const box=document.createElement('div');box.className='stat';
      const label=document.createElement('span');label.textContent=name;const strong=document.createElement('strong');
      strong.textContent=`${value} ${unit}`;box.append(label,strong);root.append(box);}
  }
  async function refreshLedger(){
    if(!stateData?.run_id){ledgerPacket=null;renderStats(null);return;}
    const query=filterQuery(),key=stateData.run_id+'|'+stateData.status+'|'+
      (stateData.progress?.fill_count??0)+'|'+query;
    if(key===lastLedgerKey)return;
    lastLedgerKey=key;
    try{
      const response=await fetch('/ledger?'+query,{cache:'no-store'});
      if(!response.ok)throw Error();
      const packet=await response.json();ledgerPacket=packet;
      renderStats(packet.statistics);
      $('export-filtered').href='/ledger.csv'+(query?'?'+query:'');
      const warning=$('ledger-warning');
      warning.hidden=packet.available&&packet.reconciled;
      warning.textContent=!packet.available?(packet.reason||'交易账本不可用。'):
        packet.reconciled?'':'账本费用与成交费用合计未完全核对。';
      accountView?.update(stateData.account||null,[],ledgerPacket);
    }catch(_){renderStats(null);ledgerPacket=null;lastLedgerKey='';}
  }
  async function refreshState(){
    try{
      const response=await fetch('/state',{cache:'no-store'});
      if(!response.ok)throw Error();
      const packet=await response.json();stateData=packet;
      text('job-title',packet.config?.name||'研究任务');
      const status=statusNames[packet.status]||'状态待核实';
      const reason=reasonNames[packet.reason]||packet.reason||'';
      text('job-state',status+(reason?' · '+reason:''));
      const percent=packet.progress?.percent;
      $('job-progress').hidden=percent==null;
      if(percent!=null)$('job-progress').value=percent;
      text('job-percent',percent==null?'—':number(percent,1)+'%');
      text('chart-note',packet.progress?`已处理 ${packet.progress.completed_bars??0} 根完成柱，${packet.progress.fill_count??0} 笔成交`:'等待历史处理');
      if(packet.chart_url&&packet.chart_url!==chartUrl){
        chartUrl=packet.chart_url;$('research-chart').src=packet.chart_url;
      }
      if(!accountView&&globalThis.QfAccountView){
        accountView=QfAccountView.create($('account-root'),{scenario:'research'});
      }
      accountView?.update(packet.account||null,[],ledgerPacket);
      await refreshLedger();
    }catch(_){
      text('job-state','任务状态暂不可用；后台计算可能仍在继续。');
    }
  }
  for(const field of filters)field.addEventListener('change',()=>{
    clearTimeout(filterTimer);filterTimer=setTimeout(refreshLedger,120);
  });
  setInterval(refreshState,1000);refreshState();
})();
