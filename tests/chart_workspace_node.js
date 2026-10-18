'use strict';
const assert=require('node:assert/strict');
global.window=global;
const listeners=new Map();
global.addEventListener=(type,fn)=>listeners.set(type,fn);
global.removeEventListener=(type,fn)=>{if(listeners.get(type)===fn)listeners.delete(type)};
global.Option=function(text,value){this.textContent=text;this.value=value;};
class E{
  constructor(){this.style={};this.dataset={};this.options=[{}];this.classList={toggle(){}};this.contentWindow={postMessage(){}};this.clientWidth=700;this.clientHeight=400;}
  addEventListener(){}remove(){}setAttribute(){}removeAttribute(){}add(o){this.options.push(o)}
  replaceChildren(...nodes){this.options=nodes;}
}
const root=new E(),roles=new Map();
root.querySelector=s=>{const role=s.match(/data-role="([^"]+)"/)[1];if(!roles.has(role))roles.set(role,new E());return roles.get(role);};
root.querySelectorAll=()=>[];
global.QfLabels={productName:()=> '螺纹钢',exchangeName:()=> '上期所',contractName:s=>s};
require('../qf/web/chart-state.js');require('../qf/web/chart-pane.js');
const pane=QfChartPane.create(root,{id:'pane-1',onActivate(){},onEscape(){},onChoose(){},onPeriod(){}});
pane.update({generation:2,status:'ready',connected:true,chart_url:'http://127.0.0.1:5',rows:[],favorites:[],
  catalog:[{continuous:'KQ.m@SHFE.rb'}],active:true,
  config:{continuous:'KQ.m@SHFE.rb',mode:'actual',period:'1m'},
  request:{revision:10},runtime:{symbol:'SHFE.rb2701',status:'ready'}});
const correct={source:roles.get('chart').contentWindow,origin:'http://127.0.0.1:5',data:{
  kind:'qf-chart-state',pane_id:'pane-1',generation:2,revision:10,symbol:'SHFE.rb2701',duration:6e10,
  viewport_width:700,viewport_height:400,status:'ready',history:{valid_count:3,years:{'2026':3}},visible:{}}};
for(const patch of [{pane_id:'pane-2'},{generation:1},{revision:9},{symbol:'DCE.m2701'},{duration:3e11}]){
  listeners.get('message')({...correct,data:{...correct.data,...patch}});assert.equal(pane.inspect().state,null);
}
listeners.get('message')({...correct,source:{}});assert.equal(pane.inspect().state,null);
listeners.get('message')({...correct,origin:'http://evil.test'});assert.equal(pane.inspect().state,null);
listeners.get('message')(correct);assert.equal(pane.inspect().state.status,'ready');
listeners.get('message')({...correct,data:{...correct.data,viewport_width:600}});
assert.equal(pane.inspect().state.status,'loading','尺寸未同步的旧绘制不能结束加载');
listeners.get('message')({...correct,data:{...correct.data,md_connected:false}});
assert.equal(root.dataset.light,'red','图表自己的行情断开，不能借后台绿灯显示已连接');
pane.dispose();assert.equal(listeners.has('message'),false);
console.log('CHART_WORKSPACE_OK');
