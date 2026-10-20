(() => {
  'use strict';
  const statusText={waiting:'等待空闲',starting:'正在启动',active:'运行中',
    warmup:'预热中',backtesting:'回测中',stopping:'停止中',saving:'保存中',
    backtest_finished:'回测完成',stopped:'已停止',failed:'失败',frozen:'已冻结',interrupted:'异常中断'};
  const percent=job=>job?.progress?.percent==null?'—':job.progress.percent+'%';
  function describe(job){return `${job?.config?.name||'未命名实验'} · ${job?.config?.continuous||job?.config?.symbol||'品种待核实'} · ${job?.config?.bar_seconds||'—'}秒 · ${statusText[job?.status]||'状态待核实'} · ${percent(job)}`;}
  function create(root,api,options={}){
    let jobs=[],selected=null,disposed=false,busy=false;
    const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text??'';return e;};
    const title=el('h3','回测任务'),capacityLabel=el('label','并发数 '),capacity=el('input');
    capacity.type='number';capacity.min='1';capacity.max='4';capacity.value='2';capacityLabel.append(capacity);
    const list=el('div');root.replaceChildren(title,capacityLabel,list);
    async function refresh(){
      if(disposed||busy)return jobs;busy=true;
      try{const response=await api.list_backtest_jobs?.();if(response?.ok){jobs=response.jobs||[];
        if(selected&&!jobs.some(job=>job.job_id===selected))selected=null;render();}}
      catch(_){ }finally{busy=false;}return jobs;
    }
    function render(){
      list.replaceChildren();
      for(const job of jobs){const card=el('article',''),head=el('button',describe(job));
        card.className='research-job-card';head.className='research-job-select';head.dataset.job=job.job_id;
        head.onclick=()=>{selected=job.job_id;render();options.onSelect?.(job);};
        if(selected===job.job_id)card.classList.add('selected');
        const actions=el('span','');
        const watch=el('button',job.watch?'暂停观看':'观看');watch.onclick=async()=>{const answer=await api.set_backtest_watch?.(job.job_id,!job.watch);if(answer?.ok){job.watch=!job.watch;render();}};
        const chart=el('button','查看图');chart.onclick=async()=>{const answer=await api.open_backtest_chart?.(job.job_id);if(answer?.ok)options.onChart?.(answer,job);};
        const stop=el('button','停止本任务');stop.disabled=!['starting','active','warmup','backtesting'].includes(job.status);
        stop.onclick=async()=>{const answer=await api.stop_backtest?.(job.job_id);if(answer?.ok)options.notice?.(answer.reason);};
        actions.append(watch,chart,stop);card.append(head,actions);list.append(card);}
      if(!jobs.length)list.append(el('p','尚未启动回测任务。'));
    }
    capacity.onchange=async()=>{const answer=await api.set_backtest_capacity?.(Number(capacity.value));if(answer?.ok)capacity.value=String(answer.capacity);};
    return {refresh,select(jobId){selected=jobId;render();},selected(){return selected;},jobs(){return jobs;},dispose(){disposed=true;}};
  }
  globalThis.QfResearchJobs={create,describe,statusText};
})();
