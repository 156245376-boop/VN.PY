window.__researchSmoke=null;window.__graphProbe=null;
addEventListener('message',e=>{if(e.data?.kind==='research-graph-probe')window.__graphProbe=e.data;});
(async()=>{const api=pywebview.api;
 const wait=async(fn,label)=>{window.__researchStage=label;for(let i=0;i<100;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error(label);};
 const assert=(v,label)=>{if(!v)throw Error(label);};
 document.querySelector('[data-view=backtests]').click();
 const runs=(await api.list_research_runs()).runs;
 let saved;
 for(const r of runs){if(r.status==='backtest_finished'&&(await api.get_research_result(r.run_id)).details?.fills.length===2){saved=r;break;}}
 assert(saved,'新进程保留已完成实验');
 await wait(()=>[...document.querySelectorAll('#research-results button')].some(b=>b.title===saved.run_id),'保存结果入口');
 [...document.querySelectorAll('#research-results button')].find(b=>b.title===saved.run_id).click();
 await wait(()=>document.querySelectorAll('#research-results .table-scroll tbody tr').length===2,'已保存成交加载完成');
 [...document.querySelectorAll('#research-content button')].find(b=>b.textContent==='查看成交K线（离线复盘）').click();
 await wait(()=>window.__graphProbe?.fills===2&&window.__graphProbe?.plots===2&&window.__graphProbe?.history?.status==='ready','无凭证重新加载成交与均线');
 assert(!window.__graphProbe.bridge&&!window.__graphProbe.invalid,'离线子页隔离且坐标有效');
 assert(!(await api.get_research_state()).running,'重开结果不启动策略');
 window.__researchSmoke={done:true,phase:'reopen',run_id:saved.run_id};
})().catch(e=>window.__researchSmoke={error:String(e),stage:window.__researchStage,probe:window.__graphProbe,text:document.querySelector('#research-results').textContent.slice(-700)});
