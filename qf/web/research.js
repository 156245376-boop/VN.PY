(() => {
  'use strict';
  const labels={created:'尚未运行',connecting:'正在连接',active:'正在运行',observing:'仅观察，不委托',
    stopped:'已停止',failed:'失败',frozen:'已冻结，需核实',backtest_finished:'回测完成',discovering:'正在查询合约',contracts_ready:'合约查询完成'};
  const reasons={terminal_bar_evidence_invalid:'末根K线完成证据核对失败，未标为完整回测',contract_range_exceeds_expiry:'结束日期超过该月份合约的到期日，请缩小日期或重新查询合约',historical_coverage_incomplete:'所选日期存在未返回的交易日，不能作为完整回测；请缩小日期或核对合约覆盖',trading_calendar_unavailable:'交易日历未能核实，已停止；请检查网络与日期范围',no_trading_days:'该区间没有交易日，请调整日期',historical_time_stalled:'历史时间长时间没有推进，已停止；请核对数据权限和网络',result_save_failed:'结果保存失败，请检查本机目录与磁盘',result_integrity_failed:'结果完整性核对未通过，不能标为完成',requested_stop:'任务已停止；不代表持仓已经平仓',flatten_confirmed:'已确认空仓且无未结委托',
    historical_replay_completed:'历史回放完成，期末持仓按市值计入',sdk_or_auth_or_permission_error:'认证、权限或SDK请求未完成，请核对凭证与数据权限',
    sdk_cost_missing:'SDK未返回有效费用、保证金或合约规格，已停止执行',underlying_changed:'所选合约不是已核实的当前主力，请重新查询并选择月份',
    connection_lost:'连接中断，本地保护无法保证继续执行',order_rejected:'委托被拒绝，已冻结后续执行',external_order:'发现本实验之外的委托，请先核实账户',
    external_trade:'发现本实验之外的成交，请先核实账户',contract_near_expiry:'合约已到期或临近到期，请核实月份',resume_incomplete:'恢复记录不完整或持仓期间缺少风险记录，请先核实',
    historical_data_invalid:'历史数据存在内部缺口、无效柱或时间异常',historical_data_missing_or_incomplete:'历史数据未返回或不完整，不能完成回测',
    backtest_statistics_missing:'SDK未返回完整统计，不能宣称回测成功',cancellation_unconfirmed:'撤单或退出状态尚未确认，请核对实际委托和仓位',
    new_run_requires_flat_account:'新模拟实验要求整个账户空仓',new_run_requires_no_orders:'新模拟实验要求账户没有未结委托',
    position_trade_mismatch:'实际持仓与本地成交记录不一致',unexpected_position:'发现超限、双向或其他合约持仓',execution_timeout:'执行等待超时，已冻结后续执行',
    contract_query_or_permission_failed:'合约查询未完成，请核对认证和权限',research_start_or_record_failed:'研究任务或本地记录未能启动',shutdown_unconfirmed:'退出清理超时，状态保留为待核实'};
  Object.assign(reasons,{capacity:'并发任务已满，正在等待空闲槽位',baseline_pending:'等待基准任务完成后运行费用压力回放',
    worker_disconnected:'回测子进程意外断开，请查看已完成记录后重新提交'});
  Object.assign(reasons,{historical_main_missing:'该日期没有可核实的历史主力映射',historical_main_invalid:'历史主力不属于所选品种',
    roll_reference_missing:'换月缺少两合约同一时刻的完成参考柱，已停止',prewarm_insufficient:'起始日前历史主力预热不足，未开始交易',
    roll_spec_incompatible:'新旧合约乘数或最小手数不兼容，已停止移仓',roll_unaffordable:'资金不足以按原手数开新，未偷偷减仓',
    roll_timeout:'移仓执行等待超时，状态待核实',roll_incomplete_at_end:'回测终点仍有未完成移仓，结果不完整',
    roll_mapping_changed:'移仓未结束主力映射再次变化，已停止',tick_data_unavailable:'所需Tick数据未返回，未降为分钟近似'});
  function describeState(s){
    const terminal=['failed','frozen','stopped','backtest_finished'].includes(s.status);
    const researchState=terminal||['connecting','active','observing'].includes(s.status),p=researchState?s.progress:null;
    const detail=reasons[s.reason]||'请核对上方运行状态';
    let notice=terminal?`${labels[s.status]}：${detail}。`:'';
    if(terminal&&s.reason==='contract_range_exceeds_expiry')notice=`回测未开始，任务已结束：合约 ${s.config?.symbol||'所选月份'} 无法覆盖结束日 ${s.config?.end||'所选日期'}。请缩短结束日，再重新查询并选择实际合约。`;
    const warming=p?.warmup_percent!=null||p?.stage==='warmup';
    const tradingStart=s.config?.start||'所选起始交易日';
    const phaseNotice=warming?(terminal?`${labels[s.status]}：结束时仍在预热，正式交易尚未开始；交易起点 ${tradingStart}。`:
      `历史预热中，不下单；正式交易从 ${tradingStart} 开始，预热图中的交叉不会产生委托。`):'';
    let progressText='';
    if(p&&terminal)progressText=`${notice} 已处理 ${p.completed_bars||0} 根完成柱、${p.fill_count||0} 笔成交；用时 ${p.elapsed_seconds??'—'} 秒。`;
    else if(p){const names={validating:'校验参数',connecting:'连接账户',history:'读取历史',warmup:'均线预热',backtesting:'运行回测',simulating:'模拟运行',saving:'保存结果'};
      let date='尚未推进到有效历史时间';try{if(p.current_ns)date=new Date(Number(BigInt(p.current_ns)/1000000n)).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});}catch(_){}
      const percent=warming?(p.warmup_percent==null?'预热进度待数据核实':`预热 ${p.warmup_percent}%`):(p.percent==null?'等待数据':p.percent+'%（历史时间）');
      progressText=`${names[p.stage]||'正在核实状态'} · ${percent} · 计算到 ${date} · 已处理 ${p.completed_bars} 根完成柱，${p.fill_count} 笔成交 · 已用 ${p.elapsed_seconds} 秒 · ${p.last_advance_age_seconds} 秒未推进 · 剩余时间暂无法估算。`;}
    if(warming)progressText+=terminal?` 停止时仍在预热，正式交易尚未开始；交易起点 ${tradingStart}。`:` ${phaseNotice}`;
    return {terminal,notice,progressText,phaseNotice,showProgress:!!p,progressValue:terminal?(p?.percent??0):warming?p?.warmup_percent:p?.percent,
      showChart:researchState&&(!terminal||!!(p?.completed_bars||p?.fill_count))};
  }
  function allowBacktestStart(last,key,now){
    return !last||last.key!==key||now-last.at>=1200;
  }
  function jobDisplayState(job){
    const aliases={waiting:'created',starting:'connecting',stopping:'active',saving:'active',
      warmup:'active',backtesting:'active',interrupted:'failed'};
    return {...job,status:aliases[job?.status]||job?.status||'created',
      running:job?.running===true,mode:'backtest',activate:false,
      progress:job?.progress||null,account:job?.account||null,risk:job?.risk||{},
      result:job?.result||null};
  }
  function create(root,api){
    let ref=null,view='strategy',disposed=false,polling=false,contractKey='',lastResult='',stress=null,commandPending=false,acceptedRequest=null,lastTerminalKey='',selectedJob=null,lastStart=null,catalog=[],ledgerCache=null,ledgerKey='';
    const el=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text||'';if(cls)e.className=cls;return e;};
    const heading=el('h2','双均线交叉 · 策略实验'),intro=el('p','金叉做多、死叉做空；使用已完成K线，反向时先平仓。');
    const picker=el('select');picker.setAttribute('aria-label','已保存实验');
    const formRoot=el('div'),actions=el('div',null,'research-actions'),notice=el('p',null,'research-notice'),state=el('p',null,'research-status'),risk=el('p');
    const progressBar=el('progress'),progressText=el('p');progressBar.max=100;progressBar.hidden=true;progressText.className='research-progress';
    const plannerRoot=el('div');plannerRoot.id='research-planner';plannerRoot.hidden=true;
    const editorDetails=el('details'),editorSummary=el('summary','新建或编辑回测策略'),editorBody=el('div');
    editorDetails.append(editorSummary,editorBody);editorBody.append(picker,formRoot,actions);
    const jobsRoot=el('div');jobsRoot.id='research-jobs';
    root.replaceChildren(heading,intro,plannerRoot,editorDetails,notice,state,progressBar,progressText,risk,jobsRoot);
    let useBacktestJobs=false,capabilityChecked=false,jobChartOpen=false,activeSlot=null;
    const jobsPanel=globalThis.QfResearchJobs?.create(jobsRoot,api,{
      showCapacity:false,
      onSelect(job){selectedJob=job.job_id;ledgerKey='';ledgerCache=null;jobChartOpen=false;liveFrame.hidden=true;liveFrame.removeAttribute('src');liveBinding=null;if(job.account)ensureAccount?.(job.account);poll();},
      onChart(answer,job){selectedJob=job.job_id;jobsPanel?.select(selectedJob);jobChartOpen=true;watch.checked=true;
        liveBinding=answer;liveJob=job.job_id;liveFrame.hidden=false;liveFrame.src=answer.url;},
      onWatch(job,enabled){if(enabled){selectedJob=job.job_id;watch.checked=true;jobChartOpen=false;poll();}
        else if(liveJob===job.job_id){liveFrame.hidden=true;liveFrame.removeAttribute('src');liveBinding=null;liveJob=null;jobChartOpen=false;}},
      notice(text){notice.textContent=text;}});
    const form=QfResearchForm.create(formRoot,{onChange(key){if(['continuous','start','end'].includes(key)){acceptedRequest=null;contractKey='';}}});
    const planner=globalThis.QfResearchPlanner?.create(plannerRoot,api,{
      onConfigure(index,item){
        activeSlot=index;editorDetails.open=true;slotApply.hidden=false;
        slotApply.textContent=`保存并应用到槽位 ${index+1}`;
        if(item?.experiment_id){
          ref={experiment_id:item.experiment_id,revision:item.revision};
          const saved=picker.selectedOptions[0]?._experiment;
          form.render(item.config||saved?.config||QfResearchForm.defaults('historical_main'));
          picker.value=item.experiment_id;form.setSaved(true);
        }else{
          ref=null;picker.value='';form.render(QfResearchForm.defaults('historical_main'));form.setSaved(false);
        }
        notice.textContent=`正在配置回测槽位 ${index+1}。`;
      },
      async onStart(plan,startOptions={}){
        const requestId=(globalThis.crypto?.randomUUID?.()||String(Date.now())+Math.random());
        const response=await api.start_backtest_batch(
          plan,requestId,startOptions.allowPartial===true);
        if(!response.ok){planner.setErrors(response.field_errors||{});notice.textContent=response.reason;return response;}
        selectedJob=response.job_ids?.[0]||null;
        await jobsPanel?.refresh();if(selectedJob)jobsPanel?.select(selectedJob);
        notice.textContent=response.reason;return response;
      },
      async onCapacity(value){const response=await api.set_backtest_capacity?.(value);
        if(response&&!response.ok)notice.textContent=response.reason;},
      onNotice(text){notice.textContent=text;},
    });
    planner?.setCapacity(1);planner?.show(false);
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
      if(!checked(response))return null;ref=response.experiment;form.setSaved(true);await refresh();notice.textContent='实验已保存 · 修订'+ref.revision;return ref;}
    const query=button('查询区间实际合约',async()=>{const c=form.readContractRequest(),response=await api.get_research_contracts(c.continuous,c.start,c.end);
      notice.textContent=response.reason;if(checked(response)){acceptedRequest={...c,request_id:response.request_id};contractKey='';}});
    const saveButton=button('保存实验',save);
    const slotApply=button('保存并应用到槽位',async()=>{
      if(activeSlot==null)return;
      const saved=await save();if(!saved)return;
      const config=structuredClone(form.read());
      planner?.configure(activeSlot,{experiment_id:ref.experiment_id,revision:ref.revision,
        name:config.name,config,include_fee_stress:planner.slots()[activeSlot]?.include_fee_stress});
      notice.textContent=`槽位 ${activeSlot+1} 已保存：${config.name}。`;
      editorDetails.open=false;
    });
    slotApply.hidden=true;
    const copy=button('复制实验',async()=>{const old=form.isLegacy;if(!old&&!await save())return;if(!ref)return;
      const name=Array.from(form.read().name).slice(0,72).join('')+' · 副本';const response=await api.copy_experiment(ref.experiment_id,ref.revision,name,old);
      if(!checked(response))return;ref=response.experiment;form.render(response.config);copy.textContent='复制实验';await refresh();notice.textContent=old?'已复制为新版拐点实验；保留旧上限，请核对新止损规则。':'已复制，可修改均线或风险参数后另行回测。';});
    const continuousCopy=button('复制为主力连续实验',async()=>{if(!ref)return;if(!form.isLegacy&&!await save())return;
      const response=await api.copy_continuous_experiment(ref.experiment_id,ref.revision,Array.from(form.read().name).slice(0,65).join('')+' · 连续副本');
      if(!checked(response))return;ref=response.experiment;form.render(response.config);form.setSaved(true);await refresh();notice.textContent='已新建主力连续副本，原实验和旧结果保留；可以选择跨年度日期。';});
    const costLabel=el('label','附加独立双倍费用回放 '),cost=el('input');cost.type='checkbox';costLabel.prepend(cost);actions.append(costLabel);
    const watchLabel=el('label','观看交易过程（只读） '),watch=el('input');watch.type='checkbox';watch.dataset.watchResearch='true';watchLabel.prepend(watch);actions.append(watchLabel);
    const liveFrame=el('iframe'),liveNote=el('p'),accountRoot=el('div');liveNote.className='research-chart-state';liveNote.hidden=true;liveFrame.className='research-live-frame';liveFrame.title='本次实验交易过程';liveFrame.hidden=true;accountRoot.hidden=true;
    let accountView=null;root.append(liveNote,liveFrame,accountRoot);
    function ensureAccount(value,nextLedger=ledgerCache){
      if(!value&&!nextLedger?.available)return;
      accountRoot.hidden=false;
      if(!accountView&&globalThis.QfAccountView)accountView=QfAccountView.create(accountRoot,{scenario:'research'});
      accountView?.update(value||null,catalog,nextLedger);
    }
    let liveBinding=null,liveJob=null,openingLive=false,latestState={};
    try{watch.checked=localStorage.getItem('qf-watch-research')==='true';}catch(_){}
    function pauseLive(){if(liveBinding?.run_id)liveFrame.contentWindow.postMessage({kind:'qf-live-pause',run_id:liveBinding.run_id,generation:liveBinding.generation,paused:!watch.checked},new URL(liveBinding.url).origin);}
    async function syncLive(s){latestState=s;const description=describeState(s);liveNote.hidden=!watch.checked;
      if(liveJob&&liveJob!==s.job_id){liveFrame.removeAttribute('src');liveBinding=null;liveJob=null;}
      liveFrame.hidden=!watch.checked||!s.job_id||!description.showChart;
      if(!description.showChart){liveNote.textContent=description.terminal?description.notice+' 本次没有可显示的K线。':'尚未启动新的回测；请先查询并选择实际合约。';
        if(liveFrame.hasAttribute('src'))liveFrame.removeAttribute('src');liveBinding=null;liveJob=null;return;}
      liveNote.textContent=description.phaseNotice||(s.job_id?'运行图只显示本次已处理的数据。':'尚未启动回测；运行后可在这里观看交易过程。');
      if(!watch.checked||!s.job_id||openingLive)return;
      if(liveBinding&&liveJob===s.job_id){pauseLive();return;}openingLive=true;
      try{const response=useBacktestJobs&&api.open_backtest_chart
          ?await api.open_backtest_chart(s.job_id):await api.open_research_live_chart();
        if(!response.ok){notice.textContent=response.reason;return;}
        liveBinding=response;liveJob=s.job_id;liveFrame.src=response.url;
      }finally{openingLive=false;}}
    watch.onchange=()=>{try{localStorage.setItem('qf-watch-research',String(watch.checked));}catch(_){}
      if(useBacktestJobs&&latestState.job_id&&api.set_backtest_watch)
        api.set_backtest_watch(latestState.job_id,watch.checked).then(()=>jobsPanel?.refresh()).catch(()=>{});
      pauseLive();syncLive(latestState).catch(()=>{notice.textContent='运行图暂不可用，后台进度仍会继续。';});};
    function liveMessage(e){if(!liveBinding||e.source!==liveFrame.contentWindow||e.origin!==new URL(liveBinding.url).origin||e.data?.generation!==liveBinding.generation)return;
      if(liveBinding.run_id&&e.data.run_id!==liveBinding.run_id)return;
      if(e.data.kind==='qf-live-ready'){liveBinding.run_id=e.data.run_id;pauseLive();}
      if(!useBacktestJobs&&e.data.kind==='qf-research-account'&&e.data.account){
        accountRoot.hidden=false;accountView?.update(e.data.account,catalog,ledgerCache);}}
    addEventListener('message',liveMessage);
    const activateLabel=el('label','允许本实验产生快期模拟委托 '),activate=el('input');activate.type='checkbox';activateLabel.prepend(activate);actions.append(activateLabel);
    const run=button('运行回测',async()=>{const intent=JSON.stringify([form.read(),cost.checked]);
      if(useBacktestJobs&&api.start_backtest){
        const startedAt=globalThis.performance?.now?.()||Date.now();
        if(!allowBacktestStart(lastStart,intent,startedAt)){notice.textContent='相同参数刚刚已提交；请稍候，避免重复任务。';return;}
        if(!await save())return;
        const requestId=(globalThis.crypto?.randomUUID?.()||String(Date.now())+Math.random());
        const response=await api.start_backtest(ref.experiment_id,ref.revision,cost.checked,requestId);
        if(!checked(response))return;lastStart={key:intent,
          at:globalThis.performance?.now?.()||Date.now()};selectedJob=response.selected_job_id;
        await jobsPanel?.refresh();jobsPanel?.select(selectedJob);lastTerminalKey='';notice.textContent='回测任务已提交，可在任务卡中切换查看。';return;
      }
      if(!await save())return;
      stress=cost.checked?{...ref}:null;
      const response=await api.start_research(ref.experiment_id,ref.revision,'backtest');if(!checked(response)){stress=null;return;}lastTerminalKey='';notice.textContent='回测任务已提交，正在核实运行状态。';});
    const paper=button('连接模拟并观察',async()=>{if(activate.checked&&!confirm('允许此策略控制快期主模拟账户并产生模拟委托？请确认账户空仓且无挂单。'))return;
      if(!await save())return;const response=await api.start_research(ref.experiment_id,ref.revision,'paper',activate.checked);checked(response);lastTerminalKey='';notice.textContent=response.reason;});
    activate.onchange=()=>paper.textContent=activate.checked?'启动模拟策略':'连接模拟并观察';
    const stopButton=button('停止任务',async()=>{stress=null;
      if(useBacktestJobs&&selectedJob&&api.stop_backtest)notice.textContent=(await api.stop_backtest(selectedJob)).reason;
      else notice.textContent=(await api.stop_research(false)).reason;});
    const flattenButton=button('平仓并停止',async()=>{stress=null;if(confirm('退出本实验拥有的快期模拟持仓并停止？需要等待真实成交确认。'))notice.textContent=(await api.stop_research(true)).reason;});
    const resultsRoot=el('div');resultsRoot.id='research-results';root.append(resultsRoot);
    let results=null;
    if(globalThis.QfResearchResults)results=QfResearchResults.create(resultsRoot,api);
    picker.onchange=()=>{const item=picker.selectedOptions[0]?._experiment;
      if(item){ref={experiment_id:item.experiment_id,revision:item.revision};form.render(item.config);}
      else {ref=null;form.render(QfResearchForm.defaults(view==='paper'?'fixed':'historical_main'));}
      form.setSaved(!!ref);
      copy.textContent=form.isLegacy?'复制为新版拐点实验':'复制实验';poll();};
    async function poll(){if(disposed||polling)return;polling=true;try{
      if(!capabilityChecked&&api.get_research_capabilities){const capability=await api.get_research_capabilities();useBacktestJobs=capability?.ok&&capability.use_backtest_jobs===true;capabilityChecked=true;}
      planner?.show(useBacktestJobs&&view!=='paper');
      let jobState=null;
      if(useBacktestJobs&&api.list_backtest_jobs&&jobsPanel){await jobsPanel.refresh();
        if(selectedJob&&!jobsPanel.jobs().some(job=>job.job_id===selectedJob)){
          selectedJob=null;jobChartOpen=false;liveBinding=null;liveJob=null;
          liveFrame.hidden=true;liveFrame.removeAttribute('src');}
        if(selectedJob){const response=await api.get_backtest_state?.(selectedJob);if(response?.ok)jobState=response.state;}}
      const s=await api.get_research_state();if(disposed)return;
      const legacyBusy=s.running,usingJob=useBacktestJobs&&!!jobState;
      const display=usingJob?jobDisplayState(jobState):s,busy=display.running===true;
      const description=describeState(display);
      if(usingJob&&jobState.run_id&&api.get_backtest_trade_ledger){
        const key=[jobState.job_id,jobState.run_id,jobState.progress?.fill_count??0,
          jobState.status].join('|');
        if(key!==ledgerKey){ledgerKey=key;
          try{const answer=await api.get_backtest_trade_ledger(jobState.job_id);
            ledgerCache=answer?.ok?answer.ledger:null;
          }catch(_){ledgerCache=null;}
        }
      }else if(!usingJob||!jobState?.run_id){ledgerCache=null;ledgerKey='';}
      form.setRunning(!usingJob&&legacyBusy&&s.status!=='discovering');
      stopButton.disabled=usingJob?!['starting','active','warmup','backtesting'].includes(jobState?.status):!(legacyBusy||s.status==='connecting');
      flattenButton.disabled=usingJob||!legacyBusy||s.mode!=='paper'||!s.activate;
      if(display.account||ledgerCache?.available)ensureAccount(display.account,ledgerCache);
      else accountRoot.hidden=true;
      if(usingJob){state.textContent=(jobState.config?.name||'任务')+' · '+(globalThis.QfResearchJobs?.statusText?.[jobState.status]||'状态待核实')+(jobState.reason?' · '+(reasons[jobState.reason]||'请核对任务状态'):'');
        state.dataset.light=jobState.running?'green':['failed','frozen'].includes(jobState.status)?'red':'yellow';}
      const request=form.readContractRequest(),matches=JSON.stringify(request)===JSON.stringify(s.contract_request);
      const mainMode=form.read().schema_version===3;
      const valid=mainMode||(matches&&(s.contracts||[]).some(c=>c.symbol===form.read().symbol)&&!form.isLegacy);
      run.hidden=view==='paper'||useBacktestJobs;costLabel.hidden=view==='paper'||useBacktestJobs;
      run.disabled=!valid||(!usingJob&&legacyBusy);
      paper.disabled=legacyBusy||busy||!valid||mainMode;
      saveButton.disabled=(!usingJob&&legacyBusy)||form.isLegacy;
      query.disabled=legacyBusy;copy.disabled=legacyBusy;
      query.hidden=mainMode;continuousCopy.hidden=mainMode||!ref;continuousCopy.disabled=legacyBusy;
      if(view==='paper'&&mainMode&&!busy)notice.textContent='当前为主力连续历史实验，仅可回测。请选择“新建实验”创建固定合约模拟模板。';
      if(!busy&&!valid&&!form.isLegacy&&!notice.textContent)notice.textContent='请先查询当前品种和日期的实际合约，再选择月份。';
      if(!usingJob){state.textContent=(labels[s.status]||'状态待核实')+(s.reason?' · '+(reasons[s.reason]||'运行状态需要核实'):'');
        state.dataset.light=['failed','frozen'].includes(s.status)?'red':legacyBusy?'green':'yellow';}
      const r=display.risk||{},account=display.account||{};
      const equity=account.equity??display.equity,commission=account.commission??display.commission;
      risk.textContent=`本实验已核实持仓：${r.side===-1?'空':r.side===1?'多':'无方向'} ${r.quantity||0} 手；初始R：${r.initial_r??'—'} 元；保护价：${r.stop_price??'—'}；阶梯：${r.stage??'—'}；权益：${equity??'—'} 元；费用：${commission??'—'} 元。`;
      if(display.config?.schema_version===3)risk.textContent+=` 当前实际主力：${display.symbol||'待核实'}；换月 ${display.roll_count??display.result?.summary?.roll_count??0} 次；已完成逻辑交易 ${display.closed_trade_count??display.result?.summary?.closed_trade_count??0} 笔。`;
      if(display.failure_context?.date)state.textContent+=` · 日期 ${display.failure_context.date} · 合约 ${display.failure_context.symbol||'待核实'} · ${display.failure_context.data_type==='mapping'?'历史主力映射':display.failure_context.data_type==='calendar'?'交易日历':'历史行情'}`;
      form.setRunState(display);
      const p=display.progress;progressBar.hidden=!description.showProgress;progressBar.dataset.terminal=String(description.terminal);
      if(p){if(description.progressValue==null)progressBar.removeAttribute('value');else progressBar.value=description.progressValue;}
      progressText.textContent=description.progressText;
      const terminalKey=JSON.stringify([display.job_id,display.run_id,display.status,display.reason]);
      if(description.terminal&&terminalKey!==lastTerminalKey){lastTerminalKey=terminalKey;notice.textContent=description.notice;
        if(display.status!=='backtest_finished')stress=null;}
      if(!(usingJob&&jobChartOpen))await syncLive(display);
      const key=JSON.stringify([s.request_id,s.contract_request,s.contracts]);if(key!==contractKey&&s.status==='contracts_ready'&&matches&&(!acceptedRequest||acceptedRequest.request_id===s.request_id)){
        contractKey=key;const selection=form.setContracts(s.contracts,form.read().symbol);
        notice.textContent=!s.contracts.length?'区间内未返回实际合约，请核对权限与日期。':!selection.eligibleCount?'返回的月份合约均不能覆盖所选结束日，请缩短结束日后重新查询；软件不会自动修改日期。':!form.read().symbol?'请选择能覆盖结束日的实际月份；列表已标明到期日。':'已返回实际合约，请核对月份、到期日与历史覆盖。';}
      const result=jobState?.result||s.result;
      if(result?.run_id&&result.run_id!==lastResult){lastResult=result.run_id;await results?.refresh();
        if(result.summary)results?.render(result.summary);
        if(stress&&display.status==='backtest_finished'){const next=stress;stress=null;const answer=await api.start_research(next.experiment_id,next.revision,'backtest',false,null,2);
          notice.textContent=answer.ok?'基准已保存；开始独立双倍费用压力回放。':answer.reason;}}
    }catch(_){state.textContent='研究状态暂不可用';}finally{polling=false;}}
    const timer=setInterval(poll,700);refresh().catch(()=>{});poll();
    return {show(next){const paperTransition=(view==='paper')!==(next==='paper');view=next;
      root.hidden=!['strategy','backtests','paper'].includes(view);
      run.hidden=view==='paper'||useBacktestJobs;
      costLabel.hidden=view==='paper'||useBacktestJobs;
      activateLabel.hidden=view!=='paper';paper.hidden=view!=='paper';
      planner?.show(useBacktestJobs&&view!=='paper');
      if(view==='paper')editorDetails.open=true;
      if(!ref&&paperTransition)form.render(QfResearchForm.defaults(view==='paper'?'fixed':'historical_main'));
      intro.textContent=view==='paper'?'快期TqKq主模拟账户：默认仅观察。资金由服务端返回，与行情图的本地模拟账户不同。':'选择双均线、品种、周期和起止日期；默认按历史主力自动移仓，可跨年回测。';},
      updateCatalog:rows=>{catalog=rows;form.setCatalog(rows);},prepareExit(){disposed=true;clearInterval(timer);form.setRunning(true);liveFrame.removeAttribute('src');return Promise.resolve();},dispose(){disposed=true;clearInterval(timer);removeEventListener('message',liveMessage);liveFrame.removeAttribute('src');results?.dispose();form.dispose();accountView?.dispose?.();}};
  }
  globalThis.QfResearch={create,describeState,allowBacktestStart,jobDisplayState};
})();
