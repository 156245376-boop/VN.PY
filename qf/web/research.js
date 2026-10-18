(() => {
  'use strict';
  const labels={created:'尚未运行',connecting:'正在连接',active:'正在运行',observing:'仅观察，不委托',
    stopped:'已停止',failed:'失败',frozen:'已冻结，需核实',backtest_finished:'回测完成',discovering:'正在查询合约',contracts_ready:'合约查询完成'};
  const reasons={requested_stop:'任务已停止；不代表持仓已经平仓',flatten_confirmed:'已确认空仓且无未结委托',
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
    let ref=null,view='strategy',disposed=false,polling=false,contractKey='',lastResult='',stress=null;
    const el=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text||'';if(cls)e.className=cls;return e;};
    const heading=el('h2','双均线交叉 · 策略实验'),intro=el('p','金叉做多、死叉做空；使用已完成K线，反向时先平仓。');
    const picker=el('select');picker.setAttribute('aria-label','已保存实验');
    const formRoot=el('div'),actions=el('div',null,'research-actions'),notice=el('p'),state=el('p',null,'research-status'),risk=el('p');
    root.replaceChildren(heading,intro,picker,formRoot,actions,notice,state,risk);
    const form=QfResearchForm.create(formRoot);
    const button=(text,fn)=>{const b=el('button',text);b.onclick=async()=>{try{await fn();}catch(_){notice.textContent='操作未完成，请核对参数、凭证和当前任务。';}};actions.append(b);return b;};
    async function refresh(){const result=await api.get_experiments();picker.replaceChildren(new Option('新建实验',''));
      for(const item of result.experiments||[]){if(!item.config)continue;const option=new Option(item.config.name+' · 修订'+item.revision,item.experiment_id);option._experiment=item;picker.add(option);}
      if(ref)picker.value=ref.experiment_id;
    }
    async function save(){const response=await api.save_experiment(form.read(),ref?.experiment_id||null);
      if(!response.ok)throw Error(response.reason);ref=response.experiment;await refresh();notice.textContent='实验已保存 · 修订'+ref.revision;return ref;}
    const query=button('查询区间实际合约',async()=>{const c=form.read(),response=await api.get_research_contracts(c.continuous,c.start,c.end);notice.textContent=response.reason;if(response.ok)contractKey='';});
    const saveButton=button('保存实验',save);
    const copy=button('复制实验',async()=>{await save();const response=await api.copy_experiment(ref.experiment_id,ref.revision,form.read().name+' · 副本');
      if(!response.ok)throw Error();ref=response.experiment;form.render(response.config);await refresh();notice.textContent='已复制，可修改均线或风险参数后另行回测。';});
    const costLabel=el('label','附加独立双倍费用回放 '),cost=el('input');cost.type='checkbox';costLabel.prepend(cost);actions.append(costLabel);
    const activateLabel=el('label','允许本实验产生快期模拟委托 '),activate=el('input');activate.type='checkbox';activateLabel.prepend(activate);actions.append(activateLabel);
    const run=button('运行回测',async()=>{await save();stress=cost.checked?{...ref}:null;
      const response=await api.start_research(ref.experiment_id,ref.revision,'backtest');if(!response.ok){stress=null;throw Error();}notice.textContent='回测已开始，分钟近似与Tick精度以运行记录为准。';});
    const paper=button('连接模拟并观察',async()=>{if(activate.checked&&!confirm('允许此策略控制快期主模拟账户并产生模拟委托？请确认账户空仓且无挂单。'))return;
      await save();const response=await api.start_research(ref.experiment_id,ref.revision,'paper',activate.checked);notice.textContent=response.reason;});
    activate.onchange=()=>paper.textContent=activate.checked?'启动模拟策略':'连接模拟并观察';
    button('停止任务',async()=>{stress=null;notice.textContent=(await api.stop_research(false)).reason;});
    button('平仓并停止',async()=>{stress=null;if(confirm('退出本实验拥有的快期模拟持仓并停止？需要等待真实成交确认。'))notice.textContent=(await api.stop_research(true)).reason;});
    const resultsRoot=el('div');resultsRoot.id='research-results';root.append(resultsRoot);
    let results=null;
    if(globalThis.QfResearchResults)results=QfResearchResults.create(resultsRoot,api);
    picker.onchange=()=>{const item=picker.selectedOptions[0]?._experiment;
      if(item){ref={experiment_id:item.experiment_id,revision:item.revision};form.render(item.config);}
      else {ref=null;form.render(QfResearchForm.defaults());}};
    async function poll(){if(disposed||polling)return;polling=true;try{const s=await api.get_research_state();if(disposed)return;
      const busy=s.running;form.setRunning(busy);for(const b of [query,saveButton,copy,run,paper])b.disabled=busy;
      state.textContent=(labels[s.status]||'状态待核实')+(s.reason?' · '+(reasons[s.reason]||'运行状态需要核实'):'');state.dataset.light=['failed','frozen'].includes(s.status)?'red':busy?'green':'yellow';
      const r=s.risk||{};risk.textContent=`实际持仓：${r.side===-1?'空':r.side===1?'多':'无方向'} ${r.quantity||0} 手；初始R：${r.initial_r??'—'} 元；保护价：${r.stop_price??'—'}；阶梯：${r.stage??'—'}；权益：${s.equity??'—'} 元；费用：${s.commission??'—'} 元。`;
      const key=JSON.stringify([s.contract_request,s.contracts]);if(key!==contractKey&&s.status==='contracts_ready'){
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
