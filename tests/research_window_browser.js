window.__researchWindowProbe=null;
(async()=>{
  const stage=label=>{window.__researchWindowStage=label;};
  const wait=async(fn,label,timeout=12000)=>{
    stage(label);const end=Date.now()+timeout;
    while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}
    throw Error(label);
  };
  const assert=(value,text)=>{if(!value)throw Error(text);};
  const bodyText=()=>document.body.textContent;
  await wait(()=>document.querySelector('#job-title')?.textContent.includes('观察窗验收'),
    '任务标题');
  await wait(()=>document.querySelector('#job-percent')?.textContent.includes('37'),
    '任务进度');
  const frame=document.querySelector('#research-chart');
  assert(frame.src.startsWith('http://127.0.0.1:'),'图表地址未绑定');
  await wait(()=>document.querySelector('.account-view'),'账户组件');
  const ledgerTab=[...document.querySelectorAll('.account-view [data-tab]')]
    .find(button=>button.dataset.tab==='ledger');
  ledgerTab.click();
  await wait(()=>document.querySelector('.account-view tbody tr'),'交易明细行');
  assert(bodyText().includes('669.58'),'统计净盈亏缺失');
  assert(bodyText().includes('3,284'),'初始止损缺失');
  assert(document.querySelector('#export-filtered').href.includes('/ledger.csv'),
    'CSV链接缺失');
  const stableRow=document.querySelector('.account-view tbody tr');
  await new Promise(r=>setTimeout(r,1200));
  assert(stableRow===document.querySelector('.account-view tbody tr')&&stableRow.isConnected,
    '状态轮询不能清空交易明细');
  const direction=document.querySelector('[data-ledger-filter=direction]');
  direction.value='-1';direction.dispatchEvent(new Event('change'));
  await wait(()=>document.querySelector('#ledger-stats').textContent.includes('0 笔'),
    '空筛选统计');
  direction.value='';direction.dispatchEvent(new Event('change'));
  await wait(()=>document.querySelector('.account-view tbody tr'),'清除筛选');
  window.__researchWindowProbe={done:true,chartSrc:frame.src};
})().catch(error=>window.__researchWindowProbe={
  error:String(error),stage:window.__researchWindowStage,
  text:document.body.innerText.slice(-1000)});
