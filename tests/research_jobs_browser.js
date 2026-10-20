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

  document.querySelector('[data-open-research]').click();
  await wait(()=>button(document,'运行回测')&&!button(document,'运行回测').disabled,
    '研究页可用');
  input('name','任务板验收');
  input('risk.risk_budget','1000');
  button(document,'运行回测').click();
  await wait(async()=>{
    const jobs=await jobList();
    return jobs.length===1&&jobs[0].status==='active';
  },'提交首个任务');
  await wait(()=>document.querySelector('.research-progress').textContent.includes('37%')
    &&!document.querySelector('#research-content progress').hidden,'显示任务进度');
  assert(document.querySelector('#research-content progress').value===37,'进度条应为37');
  assert(document.querySelector('#research-content').textContent.includes('101000'),
    '账户权益应来自当前任务');

  await wait(()=>!button(document,'运行回测').disabled,'按钮恢复');
  button(document,'运行回测').click();
  await sleep(250);
  assert((await jobList()).length===1,'快速重复点击不能创建第二个任务');

  await sleep(1300);
  await wait(()=>!button(document,'运行回测').disabled,'冷却结束');
  button(document,'运行回测').click();
  await wait(async()=>(await jobList()).length===2,'新增等待任务');
  const waiting=taskCard('等待空闲');
  assert(waiting,'应显示等待任务卡');
  const remove=button(waiting,'移除任务');
  assert(remove&&!remove.disabled,'等待任务应可移除');
  remove.click();
  await wait(async()=>(await jobList()).length===1,'移除等待任务');

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
  await wait(async()=>(await jobList())[0].status==='stopped','停止当前任务');
  await wait(()=>taskCard('已停止'),'任务卡显示已停止');
  window.__researchJobsSmoke={done:true,chartSrc};
})().catch(error=>window.__researchJobsSmoke={error:String(error),
  stage:window.__researchJobsStage,text:document.body.innerText.slice(-800)});
