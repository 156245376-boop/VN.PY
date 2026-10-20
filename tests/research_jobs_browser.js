window.__researchJobsSmoke=null;
(async()=>{
  const api=pywebview.api;
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const wait=async(fn,label,timeout=12000)=>{
    window.__researchJobsStage=label;
    const end=Date.now()+timeout;
    while(Date.now()<end){if(await fn())return;await sleep(100);}
    throw Error(label);
  };
  const assert=(value,text)=>{if(!value)throw Error(text);};
  const button=(root,text)=>[...root.querySelectorAll('button')]
    .find(item=>item.textContent===text);
  const input=(key,value)=>{const field=document.querySelector('[data-field="'+key+'"]');
    field.value=value;field.dispatchEvent(new Event('input'));field.dispatchEvent(new Event('change'));};
  const taskCard=text=>[...document.querySelectorAll('.research-job-card')]
    .find(card=>card.textContent.includes(text));
  const jobCard=status=>[...document.querySelectorAll('.research-job-select')]
    .find(node=>node.textContent.includes('· '+status+' ·'))
    ?.closest('.research-job-card');
  const jobList=async()=>(await api.list_backtest_jobs()).jobs;
  const plannerRows=()=>[...document.querySelectorAll('#research-planner .research-plan-row')];
  const configureSlot=async(index,name)=>{
    const row=plannerRows()[index];
    assert(row,'缺少槽位 '+(index+1));
    button(row,'配置策略').click();
    await wait(()=>button(document,'保存并应用到槽位 '+(index+1)),'打开槽位编辑器');
    input('name',name);input('risk.risk_budget','1000');
    button(document,'保存并应用到槽位 '+(index+1)).click();
    await wait(()=>plannerRows()[index].textContent.includes(name),'保存槽位 '+(index+1));
    await wait(()=>!button(document,'保存并应用到槽位 '+(index+1)).disabled,
      '槽位保存完成 '+(index+1));
  };
  const addAndStart=async(name,expectedJobs)=>{
    button(document,'新增回测任务').click();
    await wait(()=>plannerRows().length===1,'新增计划槽位');
    await configureSlot(0,name);
    await wait(()=>{const node=button(document,'开始新增任务');
      return node&&!node.disabled&&!node.hidden;},'开始新增按钮可用');
    const answer=await button(document,'开始新增任务').onclick();
    assert(answer?.ok,'开始新增任务返回失败');
    await wait(async()=>(await jobList()).length===expectedJobs,'新增回测入队');
  };

  document.querySelector('[data-open-research]').click();
  await wait(()=>document.querySelector('#research-planner')
    &&!document.querySelector('#research-planner').hidden,'回测计划');
  const capacity=document.querySelector('#research-planner input[type=number]');
  capacity.value='1';capacity.dispatchEvent(new Event('change'));
  await wait(()=>plannerRows().length===1,'一个计划槽位');
  await configureSlot(0,'任务A');

  const startAll=button(document,'开始全部回测');
  assert(startAll&&!startAll.disabled,'开始按钮应可用');
  startAll.click();startAll.click();
  await wait(async()=>{
    const jobs=await jobList();
    return jobs.length===1&&jobs[0].status==='active';
  },'批量提交首个任务');
  await sleep(300);
  assert((await jobList()).length===1,'快速双击不能重复提交批次');

  await wait(()=>document.querySelector('.research-progress').textContent.includes('37%')
    &&!document.querySelector('#research-content progress').hidden,'显示任务进度');
  assert(document.querySelector('#research-content progress').value===37,'进度条应为37');
  assert(document.querySelector('#research-content').textContent.includes('101,000'),
    '账户权益应来自当前任务');

  await wait(()=>document.querySelector('.account-view tbody tr'),'账户明细');
  const tabs=[...document.querySelectorAll('.account-view [data-tab]')];
  tabs.find(tab=>tab.dataset.tab==='orders').click();
  await wait(()=>document.querySelector('.account-view tbody tr'),'委托记录');
  window.__accountStableRow=document.querySelector('.account-view tbody tr');
  await sleep(1600);
  assert(window.__accountStableRow===document.querySelector('.account-view tbody tr')
    &&window.__accountStableRow.isConnected,'相同账户快照不能重建表格行');
  tabs.find(tab=>tab.dataset.tab==='trades').click();
  await wait(()=>document.querySelector('.account-view').textContent.includes('15.21')
    &&document.querySelector('.account-view').textContent.includes('669.58'),'逐笔成交费用与盈亏');
  tabs.find(tab=>tab.dataset.tab==='ledger').click();
  await wait(()=>document.querySelector('.account-view').textContent.includes('3,284')
    &&document.querySelector('.account-view').textContent.includes('669.58'),'完整交易明细');
  assert(document.querySelector('.account-view').textContent.includes('反向交叉'),'退出原因');

  await addAndStart('任务B',2);
  assert(document.querySelector('#research-planner input[type=number]').value==='1',
    '新增任务不能改变并发数');
  const waiting=jobCard('等待空闲');
  assert(waiting,'容量1时新增任务应排队');
  button(waiting,'移除任务').click();
  await wait(async()=>(await jobList()).length===1,'移除等待任务');

  await addAndStart('任务C',2);
  const promoted=jobCard('等待空闲');
  assert(promoted,'任务C应排队');
  const active=jobCard('运行中');
  assert(active,'任务A仍在运行');
  assert(button(active,'移除任务').disabled,'运行任务不能直接移除');
  button(active,'查看图').click();
  await wait(()=>{
    const frame=document.querySelector('.research-live-frame');
    return frame&&!frame.hidden&&frame.getAttribute('src');
  },'打开任务运行图');
  const chartSrc=document.querySelector('.research-live-frame').getAttribute('src');
  button(active,'停止本任务').click();
  await wait(async()=>{
    const jobs=await jobList();
    return jobs[0].status==='stopped'&&jobs[1].status==='active';
  },'停止A后任务C启动');
  await wait(()=>jobCard('已停止')&&jobCard('运行中'),'任务卡刷新停止与运行状态');
  const runningC=jobCard('运行中');
  assert(runningC,'任务C应接替运行');
  const stopCButton=button(runningC,'停止本任务');
  window.__stopCJob=stopCButton.dataset.job;
  assert(window.__stopCJob,'停止按钮缺少任务身份');
  const stoppedC=await stopCButton.onclick();
  assert(stoppedC?.ok,'停止任务C请求失败');
  await wait(async()=>(await jobList()).some(job=>
    job.job_id===window.__stopCJob&&job.status==='stopped'),'停止任务C');
  window.__researchJobsSmoke={done:true,chartSrc,stopCJob:window.__stopCJob};
})().catch(async error=>window.__researchJobsSmoke={error:String(error),
  stage:window.__researchJobsStage,text:document.body.innerText.slice(-1200),
  jobs:await jobList().catch(()=>[])});
