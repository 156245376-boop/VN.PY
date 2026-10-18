'use strict';
const assert=require('node:assert/strict');
global.window=global;
global.addEventListener=()=>{};global.removeEventListener=()=>{};
class E{
  constructor(){this.style={};this.dataset={};this.children=[];this.nodes=new Map();
    this.clientWidth=1100;this.clientHeight=900;
    this.classList={add(){},remove(){},toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  get offsetWidth(){return this.boxWidth??this.clientWidth;}
  get offsetHeight(){return this.boxHeight??this.clientHeight;}
  getBoundingClientRect(){return {width:this.rectWidth??this.clientWidth,
    height:this.rectHeight??this.clientHeight};}
  setAttribute(){}
  querySelector(selector){
    if(selector.startsWith('[data-pane='))return this.children.find(
      n=>n.dataset.pane===selector.match(/"([^"]+)"/)[1]);
    if(!this.nodes.has(selector))this.nodes.set(selector,new E());
    return this.nodes.get(selector);
  }
}
global.document={createElement:()=>new E(),body:new E()};
global.QfChartPane={create(node,options){node.dataset.pane=options.id;
  node.activate=()=>options.onActivate(options.id);
  return {update(){},setExpanded(){},dispose(){},inspect:()=>({state:null}),send(){}};}};
global.QfAccountView={create:()=>({update(){},setCollapsed(){}})};
require('../qf/web/chart-state.js');require('../qf/web/chart-drawings.js');
require('../qf/web/chart-save.js');require('../qf/web/chart-workspace.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function fixture(layout='quad'){
  const root=new E(),config=QfChartState.defaults();config.layout=layout;
  for(const p of config.panes)p.continuous='KQ.m@SHFE.rb';
  const calls=[],saved=[];
  const workspace=QfChartWorkspace.create(root,{config,
    onConfig:async c=>{saved.push(c);return {ok:true};},
    onView:req=>new Promise(resolve=>calls.push({req,resolve}))});
  workspace.update({generation:1,status:'ready',connected:true,visible_symbols:[],
    catalog:['KQ.m@SHFE.rb','KQ.m@DCE.m','KQ.m@CZCE.OI'].map(continuous=>({continuous})),
    rows:[],favorites:[],panes:[]});
  calls[0].resolve({ok:true});await workspace.flush();
  return {root,workspace,calls,saved};
}
(async()=>{
  const fractional=await fixture('columns'),scroll=fractional.root.querySelector('.chart-grid-scroll');
  Object.assign(scroll,{clientWidth:2509,clientHeight:905,boxWidth:2509,boxHeight:905,
    rectWidth:2508.6667,rectHeight:904.3125});
  fractional.root.querySelector('#expand-workspace').onclick();
  const fractionalGrid=fractional.root.querySelector('.chart-grid');
  assert.ok(parseFloat(fractionalGrid.style.width)<=2498.6667,
    '整数 clientWidth 向上取整不能让图表超出小数可用宽度并触发滚动条循环');
  assert.ok(parseFloat(fractionalGrid.style.height)<=894.3125,
    '整数 clientHeight 向上取整不能让图表超出小数可用高度');
  Object.assign(scroll,{clientWidth:2493,clientHeight:890});
  fractional.root.querySelector('#expand-workspace').onclick();
  fractional.root.querySelector('#expand-workspace').onclick();
  assert.ok(parseFloat(fractionalGrid.style.width)<=2482.6667,
    '已有纵向滚动条时仍须扣除小数取整误差');
  assert.ok(parseFloat(fractionalGrid.style.height)<=879.3125,
    '已有横向滚动条时仍须扣除小数取整误差');
  fractional.workspace.dispose();
  const f=await fixture(),grid=f.root.querySelector('.chart-grid');
  grid.querySelector('[data-pane="pane-2"]').activate();
  const divider=grid.children.find(n=>n.className==='chart-split split-column');
  divider.onkeydown({key:'ArrowRight',preventDefault(){}});
  const link=f.root.querySelector('#link-products');link.onchange({target:{checked:true}});
  await f.workspace.flush();
  assert.equal(f.workspace.getConfig().active,'pane-2');
  assert.equal(f.workspace.getConfig().split.column,.52);
  f.workspace.choose('KQ.m@DCE.m');
  f.calls[1].resolve({ok:false,reason:'capacity'});await f.workspace.flush();
  const reverted=f.workspace.getConfig();
  assert.equal(reverted.active,'pane-2','拒绝品种修改不能撤销活动格');
  assert.equal(reverted.split.column,.52,'拒绝品种修改不能撤销已保存的分隔比例');
  assert.equal(reverted.linked,true);
  assert.ok(reverted.panes.every(p=>p.continuous==='KQ.m@SHFE.rb'));
  assert.deepEqual(f.saved.at(-1),reverted,'回退后的正确布局也必须持久化');
  f.workspace.dispose();

  const g=await fixture();
  g.workspace.choose('KQ.m@DCE.m');
  g.workspace.choose('KQ.m@CZCE.OI');
  g.calls[1].resolve({ok:true});await tick();
  g.calls[2].resolve({ok:false,reason:'capacity'});await g.workspace.flush();
  assert.equal(g.workspace.getConfig().panes[0].continuous,'KQ.m@DCE.m',
    '旧请求成功但已被更新请求取代时，仍须成为后续失败的回退基准');
  assert.equal(g.saved.at(-1).panes[0].continuous,'KQ.m@DCE.m');
  g.workspace.dispose();console.log('CHART_CONTROLLER_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
