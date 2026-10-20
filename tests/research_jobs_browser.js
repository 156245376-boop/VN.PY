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
  };

  document.querySelector('[data-open-research]').click();
  await wait(()=>document.querySelector('#research-planner')
    &&!document.querySelector('#research-planner').hidden,'回测计划');
  const capacity=document.querySelector('#research-planner input[type=number]');
  capacity.value='2';capacity.dispatchEvent(new Event('change'));
  await wait(()=>plannerRows().length===2,'创建两个槽位');
  await configureSlot(0,'任务A');
  await configureSlot(1,'任务B');

  const startAll=button(document,'开始全部回测');
  assert(startAll&&!startAll.disabled,'开始按钮应可用');
  startAll.click();startAll.click();
  await wait(async()=>{
    const jobs=await jobList();
    return jobs.length===2&&jobs.every(job=>job.status==='active');
  },'批量提交两个任务');
  await sleep(300);
  assert((await jobList()).length===2,'快速双击不能重复提交批次');

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

  const active=taskCard('运行中');
  assert(active,'应保留运行任务卡');
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
    return jobs.some(job=>job.status==='stopped');
  },'停止当前任务');
  await wait(()=>taskCard('已停止'),'任务卡显示已停止');
  window.__researchJobsSmoke={done:true,chartSrc};
})().catch(error=>window.__researchJobsSmoke={error:String(error),
  stage:window.__researchJobsStage,text:document.body.innerText.slice(-1000)});
