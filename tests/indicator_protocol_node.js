'use strict';
const assert=require('node:assert/strict');global.window=global;
require('../qf/web/indicator-controller.js');require('../qf/web/native-indicator-data.js');
let submits=0,painted=0;const source={},identity={pane_id:'pane-1',generation:1,chart_revision:2,symbol:'SHFE.rb2701',period:'1m'};
const view={source,origin:'http://127.0.0.1:8000',identity,send(){}};
const c=QfIndicatorController.create({getPane:()=>view,config:{panes:{'pane-1':{items:[]}}},
  submit:async()=>{submits++;return {ok:true,job_id:'job'};},poll:async()=>({job:{status:'ready',identity:{...identity,settings_revision:1,request_id:1,data_revision:'a'},result:{series:[]}}}),
  save:async()=>({ok:true}),onResult:()=>painted++,onNotice(){},delay:0});
const payload={kind:'qf-indicator-data',...identity,settings_revision:1,request_id:1,data_revision:'a',rows:[],visible:[0,1],price_tick:1,coverage_end_ns:'1700000000000000000'};
const chart={symbol:identity.symbol,price_ticks:.2,chartCtrl:{range:{leftId:0,rightId:1}},mainSeries:{data:{
  0:{datetime:1700000000000000000,open:10,high:12,low:9,close:11,volume:2,close_oi:4},
  1:{datetime:1700000060000000000,open:11,high:12,low:9,close:11,volume:3,close_oi:4}}}};
global.QfNativeTools={intervals:c=>Object.entries(c.mainSeries.data).map(([id,r])=>({id:Number(id),time:r.datetime,start:r.datetime,end:r.datetime+60000000000}))};
const before=QfNativeIndicatorData.snapshot(chart,{symbol:identity.symbol,settings:{items:[]}});
chart.mainSeries.data[1].volume=7;
const after=QfNativeIndicatorData.snapshot(chart,{symbol:identity.symbol,settings:{items:[]}});
assert.equal(before.rows[1].volume,3);assert.equal(after.rows[1].volume,7);
(async()=>{
  c.sync();
  c.onMessage({source:{},origin:view.origin,data:payload});
  c.onMessage({source,origin:'http://evil.test',data:payload});
  c.onMessage({source,origin:view.origin,data:{...payload,chart_revision:1}});
  await new Promise(r=>setTimeout(r,20));assert.equal(submits,0);
  c.onMessage({source,origin:view.origin,data:payload});
  await new Promise(r=>setTimeout(r,20));assert.equal(submits,1);
  c.configure('pane-1',{items:[{id:'ma',type:'ma',visible:true,params:{periods:[5]},
    height:160,style:{colors:['#123456'],width:2,side:'right',width_pct:25,transparency:45,poc:true}}]});
  await c.poll();assert.equal(painted,0,'旧设置结果不能画回');
  c.setVisible('pane-1',false);c.onMessage({source,origin:view.origin,data:payload});
  await new Promise(r=>setTimeout(r,20));assert.equal(submits,1);
  await c.flush();c.dispose();console.log('INDICATOR_PROTOCOL_OK');
})().catch(e=>{c.dispose();console.error(e);process.exitCode=1;});
