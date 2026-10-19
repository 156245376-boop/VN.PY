(() => {
  'use strict';
  const labels={created:'尚未运行',connecting:'正在连接',active:'正在运行',observing:'仅观察，不委托',
    stopped:'已停止',failed:'失败',frozen:'已冻结，需核实',backtest_finished:'回测完成',discovering:'正在查询合约',contracts_ready:'合约查询完成'};
  const reasons={historical_coverage_incomplete:'所选日期存在未返回的交易日，不能作为完整回测；请缩小日期或核对合约覆盖',trading_calendar_unavailable:'交易日历未能核实，已停止；请检查网络与日期范围',no_trading_days:'该区间没有交易日，请调整日期',historical_time_stalled:'历史时间长时间没有推进，已停止；请核对数据权限和网络',result_save_failed:'结果保存失败，请检查本机目录与磁盘',result_integrity_failed:'结果完整性核对未通过，不能标为完成',requested_stop:'任务已停止；不代表持仓已经平仓',flatten_confirmed:'已确认空仓且无未结委托',
    historical_replay_completed:'历史回放完成，期末持仓按市值计入',sdk_or_auth_or_permission_error:'认证、权限或SDK请求未完成，请核对凭证与数据权限',
    sdk_cost_missing:'SDK未返回有效费用、保证金或合约规格，已停止执行',underlying_changed:'所选合约不是已核实的当前主力，请重新查询并选择月份',
    connection_lost:'连接中断，本地保护无法保证继续执行',order_rejected:'委托被拒绝，已冻结后续执行',external_order:'发现本实验之外的委托，请先核实账户',
    external_trade:'发现本实验之外的成交，请先核实账户',contract_near_expiry:'合约已到期或临近到期，请核实月份',resume_incomplete:'恢复记录不完整或持仓期间缺少风险记录，请先核实',
    historical_data_invalid:'历史数据存在内部缺口、无效柱或时间异常',historical_data_missing_or_incomplete:'历史数据未返回或不完整，不能完成回测',
    backtest_statistics_missing:'SDK未返回完整统计，不能宣称回测成功',cancellation_unconfirmed:'撤单或退出状态尚未确认，请核对实际委托和仓位',
    new_run_requires_flat_account:'新模拟实验要求整个账户空仓',new_run_requires_no_orders:'新模拟实验要求账户没有未结委托',
    position_trade_mismatch:'实际持仓与本地成交记录不一致',unexpected_position:'发现超限、双向或其他合约持仓',execution_timeout:'执行等待超时，已冻结后续执行',
    contract_query_or_permission_failed:'合约查询未完成，请核对认证和权限',research_start_or_record_failed:'研究任务或本地记录未能启动',shutdown_unconfirmed:'退出清理超时，状态保留为待核实'};
  function create(root,api){
    let ref=null,view='strategy',disposed=false,polling=false,contractKey='',lastResult='',stress=null,commandPending=false,acceptedRequest=null;
    const el=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text||'';if(cls)e.className=cls;return e;};
    const heading=el('h2','双均线交叉 · 策略实验'),intro=el('p','金叉做多、死叉做空；使用已完成K线，反向时先平仓。');
    const picker=el('select');picker.setAttribute('aria-label','已保存实验');
    const formRoot=el('div'),actions=el('div',null,'research-actions'),notice=el('p'),state=el('p',null,'research-status'),risk=el('p');
    const progressBar=el('progress'),progressText=el('p');progressBar.max=100;progressBar.hidden=true;progressText.className='research-progress';
    root.replaceChildren(heading,intro,picker,formRoot,actions,notice,state,progressBar,progressText,risk);
    const form=QfResearchForm.create(formRoot,{onChange(key){if(['continuous','start','end'].includes(key)){acceptedRequest=null;contractKey='';}}});
    function checked(response){if(response.ok){form.showErrors({});return response;}
      form.showErrors(response.field_errors||{});notice.textContent=response.reason||'操作未完成，请重新核对。';return null;}
    const button=(text,fn)=>{const b=el('button',text);b.onclick=async()=>{if(commandPending)return;commandPending=true;b.disabled=true;
      try{await fn();}catch(_){notice.textContent='操作未完成，请核对参数、凭证和当前任务。';}
      finally{commandPending=false;b.disabled=false;await poll();}};actions.append(b);return b;};
    async function refresh(){const result=await api.get_experiments();picker.replaceChildren(new Option('新建实验',''));
      for(const item of result.experiments||[]){if(!item.config)continue;const option=new Option(item.config.name+' · 修订'+item.revision,item.experiment_id);option._experiment=item;picker.add(option);}
      if(ref)picker.value=ref.experiment_id;
    }
    async function save(){const response=await api.save_experiment(form.read(),ref?.experiment_id||null);
      if(!checked(response))return null;ref=response.experiment;await refresh();notice.textContent='实验已保存 · 修订'+ref.revision;return ref;}
    const query=button('查询区间实际合约',async()=>{const c=form.readContractRequest(),response=await api.get_research_contracts(c.continuous,c.start,c.end);
      notice.textContent=response.reason;if(checked(response)){acceptedRequest={...c,request_id:response.request_id};contractKey='';}});
    const saveButton=button('保存实验',save);
    const copy=button('复制实验',async()=>{const old=form.isLegacy;if(!old&&!await save())return;if(!ref)return;
      const name=Array.from(form.read().name).slice(0,72).join('')+' · 副本';const response=await api.copy_experiment(ref.experiment_id,ref.revision,name,old);
      if(!checked(response))return;ref=response.experiment;form.render(response.config);copy.textContent='复制实验';await refresh();notice.textContent=old?'已复制为新版拐点实验；保留旧上限，请核对新止损规则。':'已复制，可修改均线或风险参数后另行回测。';});
    const costLabel=el('label','附加独立双倍费用回放 '),cost=el('input');cost.type='checkbox';costLabel.prepend(cost);actions.append(costLabel);
    const activateLabel=el('label','允许本实验产生快期模拟委托 '),activate=el('input');activate.type='checkbox';activateLabel.prepend(activate);actions.append(activateLabel);
    const run=button('运行回测',async()=>{if(!await save())return;stress=cost.checked?{...ref}:null;
      const response=await api.start_research(ref.experiment_id,ref.revision,'backtest');if(!checked(response)){stress=null;return;}notice.textContent='回测已开始，分钟近似与Tick精度以运行记录为准。';});
    const paper=button('连接模拟并观察',async()=>{if(activate.checked&&!confirm('允许此策略控制快期主模拟账户并产生模拟委托？请确认账户空仓且无挂单。'))return;
      if(!await save())return;const response=await api.start_research(ref.experiment_id,ref.revision,'paper',activate.checked);checked(response);notice.textContent=response.reason;});
    activate.onchange=()=>paper.textContent=activate.checked?'启动模拟策略':'连接模拟并观察';
    button('停止任务',async()=>{stress=null;notice.textContent=(await api.stop_research(false)).reason;});
    button('平仓并停止',async()=>{stress=null;if(confirm('退出本实验拥有的快期模拟持仓并停止？需要等待真实成交确认。'))notice.textContent=(await api.stop_research(true)).reason;});
    const resultsRoot=el('div');resultsRoot.id='research-results';root.append(resultsRoot);
    let results=null;
    if(globalThis.QfResearchResults)results=QfResearchResults.create(resultsRoot,api);
    picker.onchange=()=>{const item=picker.selectedOptions[0]?._experiment;
      if(item){ref={experiment_id:item.experiment_id,revision:item.revision};form.render(item.config);}
      else {ref=null;form.render(QfResearchForm.defaults());}
      copy.textContent=form.isLegacy?'复制为新版拐点实验':'复制实验';poll();};
    async function poll(){if(disposed||polling)return;polling=true;try{const s=await api.get_research_state();if(disposed)return;
      const busy=s.running;form.setRunning(busy&&s.status!=='discovering');for(const b of [query,saveButton,copy,run,paper])b.disabled=busy;
      const request=form.readContractRequest(),matches=JSON.stringify(request)===JSON.stringify(s.contract_request);
      const valid=matches&&(s.contracts||[]).some(c=>c.symbol===form.read().symbol)&&!form.isLegacy;
      run.disabled=paper.disabled=busy||!valid;saveButton.disabled=busy||form.isLegacy;
      if(!busy&&!valid&&!form.isLegacy&&!notice.textContent)notice.textContent='请先查询当前品种和日期的实际合约，再选择月份。';
      state.textContent=(labels[s.status]||'状态待核实')+(s.reason?' · '+(reasons[s.reason]||'运行状态需要核实'):'');state.dataset.light=['failed','frozen'].includes(s.status)?'red':busy?'green':'yellow';
      const r=s.risk||{};risk.textContent=`本实验已核实持仓：${r.side===-1?'空':r.side===1?'多':'无方向'} ${r.quantity||0} 手；初始R：${r.initial_r??'—'} 元；保护价：${r.stop_price??'—'}；阶梯：${r.stage??'—'}；权益：${s.equity??'—'} 元；费用：${s.commission??'—'} 元。`;
      const p=s.progress,stageNames={validating:'校验参数',connecting:'连接账户',history:'读取历史',warmup:'均线预热',backtesting:'运行回测',simulating:'模拟运行',saving:'保存结果',completed:'回测完成',failed:'失败',frozen:'已冻结',stopped:'已停止'};
      progressBar.hidden=!p;if(p){if(p.percent==null)progressBar.removeAttribute('value');else progressBar.value=p.percent;
        let date='尚未推进到有效历史时间';try{if(p.current_ns)date=new Date(Number(BigInt(p.current_ns)/1000000n)).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});}catch(_){}
        progressText.textContent=`${stageNames[p.stage]||'状态待核实'} · ${p.percent==null?'等待数据':p.percent+'%（历史时间）'} · 计算到 ${date} · 已处理 ${p.completed_bars} 根完成柱，${p.fill_count} 笔成交 · 已用 ${p.elapsed_seconds} 秒 · ${p.last_advance_age_seconds} 秒未推进 · 剩余时间暂无法估算。`;}
      const key=JSON.stringify([s.request_id,s.contract_request,s.contracts]);if(key!==contractKey&&s.status==='contracts_ready'&&matches&&(!acceptedRequest||acceptedRequest.request_id===s.request_id)){
        contractKey=key;form.setContracts(s.contracts,form.read().symbol);notice.textContent=s.contracts.length?'已返回实际合约，请核对月份与历史覆盖。':'区间内未返回实际合约，请核对权限与日期。';}
      if(s.result?.run_id&&s.result.run_id!==lastResult){lastResult=s.result.run_id;await results?.refresh();
        if(s.result.summary)results?.render(s.result.summary);
        if(stress&&s.status==='backtest_finished'){const next=stress;stress=null;const answer=await api.start_research(next.experiment_id,next.revision,'backtest',false,null,2);
          notice.textContent=answer.ok?'基准已保存；开始独立双倍费用压力回放。':answer.reason;}}
    }catch(_){state.textContent='研究状态暂不可用';}finally{polling=false;}}
    const timer=setInterval(poll,700);refresh().catch(()=>{});poll();
    return {show(next){view=next;root.hidden=!['strategy','backtests','paper'].includes(view);run.hidden=view==='paper';costLabel.hidden=view==='paper';activateLabel.hidden=view!=='paper';paper.hidden=view!=='paper';
      intro.textContent=view==='paper'?'快期TqKq主模拟账户：默认仅观察。资金由服务端返回，与行情图的本地模拟账户不同。':'选择双均线、实际合约、周期、日期与仓位规则；回测结果不证明策略有效。';},
      updateCatalog:rows=>form.setCatalog(rows),prepareExit(){disposed=true;clearInterval(timer);form.setRunning(true);return Promise.resolve();},dispose(){disposed=true;clearInterval(timer);results?.dispose();form.dispose();}};
  }
  globalThis.QfResearch={create};
})();
