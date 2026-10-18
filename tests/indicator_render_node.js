'use strict';const assert=require('node:assert/strict');global.window=global;
require('../qf/web/native-indicator-render.js');
const R=QfNativeIndicatorRender,profile={total_volume:20,poc:11,bins:[
  {low:9,high:10,volume:2,share:.1},{low:10,high:11,volume:8,share:.4},{low:11,high:12,volume:10,share:.5}]};
const style={side:'right',width_pct:25,transparency:45};
const boxes=R.profileGeometry(profile,style,400,v=>200-v*10);
assert.deepEqual(boxes.map(b=>b.width),[20,80,100]);assert.equal(boxes[2].x,300);
assert.equal(boxes[0].opacity,.55);assert.equal(boxes[2].fill,'rgb(220,45,40)');
assert.equal(R.profileGeometry(profile,{...style,side:'left'},400,v=>v)[0].x,0);
const source={3:{datetime:1700000000000000000},4:{datetime:1700000060000000000}};
const data=R.lineData([{id:3,time_ns:'1700000000000000000',value:null},
  {id:4,time_ns:'1700000060000000000',value:3}],source);
assert.equal(data[3],undefined);assert.equal(data[4].value,3);
assert.equal(R.lineData([{id:4,time_ns:'1800000000000000000',value:3}],source)[4],undefined);
const note=R.dataNote({calculation_start_ns:'1700000000000000000',warmup:'预热说明',profiles:[{}]},'1h');
assert.match(note,/1小时/);assert.match(note,/2023-11-15/);assert.match(note,/未收盘柱/);
console.log('INDICATOR_RENDER_OK');
