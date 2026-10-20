'use strict';
const assert=require('node:assert/strict');

class Element {
  constructor(tag){this.tagName=tag;this.textContent='';this.className='';this.dataset={};
    this.children=[];this.disabled=false;this.hidden=false;this.value='';
    this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};}
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  click(){return this.onclick?.({});}
}
global.document={createElement:tag=>new Element(tag)};
require('../qf/web/research-planner.js');

function all(root){
  const result=[];const visit=node=>{result.push(node);for(const child of node.children||[])visit(child);};
  visit(root);return result;
}
function byText(root,text){return all(root).find(node=>node.textContent===text);}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

(async()=>{
  const root=new Element('div'),starts=[],configured=[];
  const planner=QfResearchPlanner.create(root,{},{
    onStart:async plan=>{starts.push(plan);return {ok:true};},
    onConfigure:(index,item)=>configured.push([index,item]),
  });
  planner.setCapacity(2);
  assert.equal(planner.slots().length,2);
  assert.equal(starts.length,0,'改变并发数不能启动任务');
  assert.equal(byText(root,'开始全部回测').disabled,true);
  byText(root,'配置策略').click();
  assert.equal(configured[0][0],0);
  planner.configure(0,{experiment_id:'a'.repeat(32),revision:1,name:'A'});
  planner.configure(1,{experiment_id:'b'.repeat(32),revision:1,name:'B',
    include_fee_stress:true});
  assert.equal(byText(root,'开始全部回测').disabled,false);
  const response=await byText(root,'开始全部回测').click();
  assert.equal(response.ok,true);
  assert.deepEqual(starts[0],{capacity:2,slots:[
    {experiment_id:'a'.repeat(32),revision:1,include_fee_stress:false},
    {experiment_id:'b'.repeat(32),revision:1,include_fee_stress:true},
  ]});
  assert.throws(()=>QfResearchPlanner.buildPlan(2,[
    {experiment_id:'a'.repeat(32),revision:1}]));
  assert.throws(()=>QfResearchPlanner.buildPlan(1,[
    {experiment_id:'private',revision:1}]));
  console.log('RESEARCH_PLANNER_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
