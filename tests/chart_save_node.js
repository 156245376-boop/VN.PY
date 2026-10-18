'use strict';
const assert=require('node:assert/strict');global.window=global;
require('../qf/web/chart-save.js');
(async()=>{
  const calls=[],messages=[];let release;
  const queue=QfLayoutSaves.create(config=>{calls.push(config);return new Promise(r=>release=r)},r=>messages.push(r));
  queue.submit({value:1});queue.submit({value:2});queue.submit({value:3});
  assert.equal(calls.length,1,'仅允许单个保存写入');
  release({ok:true});await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls,[{value:1},{value:3}]);assert.equal(messages.length,0,'旧确认不能显示为最新已保存');
  release({ok:false,reason:'disk'});await queue.flush();
  assert.equal(messages.length,1);assert.equal(messages[0].ok,false);
  console.log('CHART_SAVE_OK');
})().catch(e=>{console.error(e);process.exitCode=1});
