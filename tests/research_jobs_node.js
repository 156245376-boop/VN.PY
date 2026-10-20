'use strict';
const assert=require('node:assert/strict');

class Element {
  constructor(tag){
    this.tagName=tag;this.textContent='';this.className='';this.dataset={};this.children=[];
    this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};
  }
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  click(){return this.onclick?.({});}
}
global.document={createElement:tag=>new Element(tag)};
require('../qf/web/research-jobs.js');
require('../qf/web/research.js');

function buttons(node){
  const found=[];
  if(node.tagName==='button')found.push(node);
  for(const child of node.children||[])found.push(...buttons(child));
  return found;
}
function byText(root,text){
  return buttons(root).find(button=>button.textContent===text);
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

(async()=>{
  const active={job_id:'a'.repeat(32),status:'active',running:true,watch:false,
    config:{name:'双均线实验',continuous:'KQ.m@SHFE.rb',bar_seconds:60},
    progress:{percent:37,completed_bars:120,fill_count:2},account:{equity:'101000'},
    risk:{quantity:1}};
  const waiting={job_id:'b'.repeat(32),status:'waiting',running:false,watch:false,
    config:{name:'等待实验',continuous:'KQ.m@SHFE.rb',bar_seconds:60},
    progress:null,account:null,risk:{}};
  const jobs=[active,waiting], calls=[], watched=[];
  const api={
    list_backtest_jobs:async()=>({ok:true,jobs}),
    remove_backtest:async id=>{calls.push(['remove',id]);
      jobs.splice(jobs.findIndex(job=>job.job_id===id),1);return {ok:true,reason:'已移除'};},
    set_backtest_watch:async(id,enabled)=>{calls.push(['watch',id,enabled]);return {ok:true};},
    open_backtest_chart:async id=>({ok:true,url:'http://127.0.0.1/chart',run_id:'run',generation:1}),
  };
  const root=new Element('div');
  const panel=QfResearchJobs.create(root,api,{
    onWatch:(job,enabled)=>watched.push([job.job_id,enabled]),
    notice:()=>{},
  });
  await panel.refresh();
  assert.ok(byText(root,'双均线实验 · KQ.m@SHFE.rb · 60秒 · 运行中 · 37%'),
    '应显示包含进度和中文品种的任务卡');
  byText(root,'观看').click();await tick();
  assert.deepEqual(calls.at(-1),['watch',active.job_id,true]);
  assert.deepEqual(watched.at(-1),[active.job_id,true]);
  const remove=buttons(root).find(button=>button.textContent==='移除任务'&&!button.disabled);
  assert.ok(remove,'等待任务必须可以移除');
  assert.ok(buttons(root).filter(button=>button.textContent==='查看图')[1].disabled,
    '等待任务不应打开空运行图');
  remove.click();await tick();
  assert.deepEqual(calls.at(-1),['remove',waiting.job_id]);
  assert.equal(jobs.length,1);

  const now=1000;
  assert.equal(QfResearch.allowBacktestStart(null,'exp:1',now),true);
  assert.equal(QfResearch.allowBacktestStart({key:'exp:1',at:now-400},'exp:1',now),false);
  assert.equal(QfResearch.allowBacktestStart({key:'exp:1',at:now-400},'exp:2',now),true);
  assert.equal(QfResearch.allowBacktestStart({key:'exp:1',at:now-1400},'exp:1',now),true);

  const display=QfResearch.jobDisplayState(active);
  assert.equal(display.job_id,active.job_id);
  assert.equal(display.running,true);
  assert.equal(display.progress.percent,37);
  assert.equal(QfResearch.describeState(display).showChart,true);
  assert.equal(QfResearch.jobDisplayState(waiting).status,'created');
  console.log('RESEARCH_JOBS_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
