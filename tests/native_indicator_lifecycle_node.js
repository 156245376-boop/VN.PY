'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const listeners={},sent=[],chart={symbol:'SHFE.rb2701'};
let tick;
const view={instrumentId:chart.symbol,duration:6e10,mainType:'candle',$tqsdk:{quotesWs:{ws:{readyState:1}}}};
const parent={postMessage:d=>sent.push(d)},context={console,parent,qfParentOrigin:'http://parent',
  document:{body:null,querySelector:s=>s==='.tq-top-view'?{__vue__:view}:null,addEventListener(){}},
  MutationObserver:class{observe(){}disconnect(){}},queueMicrotask,Date,Math,
  addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn),setInterval:fn=>(tick=fn,1),clearInterval(){},
  QfLabels:{quoteUnit:()=> '元/吨'},QfNativeHistory:{inspect:()=>({status:'ready',symbol:chart.symbol}),getChart:()=>chart},
  QfNativeIndicatorData:{checkedSnapshot:()=>({rows:[{id:1}],visible:[1,1]})},
  QfNativeIndicatorRender:{attach:()=>({chart,configure(){},apply(){}})},
  QfNativeVpRange:{attach:()=>({configure(){}})}};
context.window=context;vm.createContext(context);
vm.runInContext(fs.readFileSync('qf/web/native-labels.js','utf8'),context);
function message(data){for(const fn of listeners.message)fn({source:parent,origin:context.qfParentOrigin,data});}
const identity={pane_id:'pane-1',generation:1,revision:1,symbol:chart.symbol,period:'1m'};
message({kind:'qf-chart-labels',...identity,catalog:[]});
const config={kind:'qf-indicator-config',...identity,chart_revision:1,settings_revision:1,settings:{items:[]},enabled:true};
message(config);tick();tick();
assert.equal(sent.filter(d=>d.kind==='qf-indicator-data').length,1,'相同快照去重');
message({...config,enabled:false});tick();message(config);tick();
assert.equal(sent.filter(d=>d.kind==='qf-indicator-data').length,2,'静态数据隐藏再显示必须重新计算');
console.log('NATIVE_INDICATOR_LIFECYCLE_OK');
