const assert=require('node:assert/strict');
global.window=global;
require('../qf/web/account-view.js');
require('../qf/web/native-replay.js');
const rows=QfAccountView.metricRows({summary:{balance:100000,float_profit:0,margin:null,
  commission:3,commission_total:'10',roll_commission:'4',actual_fill_count:161,
  closed_trade_count:80,open_position:10}},'research');
const byName=Object.fromEntries(rows.map(row=>[row[0],row.slice(1)]));
assert.deepEqual(byName['浮动盈亏'],[0,'元']);
assert.deepEqual(byName['保证金占用'],['未记录','元']);
assert.deepEqual(byName['实际成交'],[161,'笔']);
assert.deepEqual(byName['完整交易'],[80,'笔']);
assert.deepEqual(byName['未结束持仓'],[10,'手']);
assert.ok(QfAccountView.stateText({status:'last_snapshot',time_ns:'100'},'research').includes('末次账户快照'));
assert.ok(QfAccountView.stateText(null,'market').includes('不是快期模拟账户'));
const bars=Array.from({length:5},(_,i)=>({time_ns:String(100+i*60),end_ns:String(160+i*60),close:100+i}));
const geometry=QfNativeReplay.protectionGeometry([
  {start_ns:'40',end_ns:'400',display_price:'0',kind:'initial',actual_price:'3300',source_symbol:'SHFE.rb2505'},
  {start_ns:'100',end_ns:'400',display_price:'-4',kind:'active',actual_price:'3296',source_symbol:'SHFE.rb2505'},
],bars,60);
assert.equal(geometry.length,2);
assert.equal(geometry[0].a,0);assert.equal(geometry[0].b,4);
assert.equal(geometry[0].price,0);
assert.equal(geometry[1].price,-4);
console.log('RESEARCH_OBSERVATION_OK');
