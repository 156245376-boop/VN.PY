const assert=require('node:assert/strict');
require('../qf/web/research.js');require('../qf/web/research-form.js');
const state={status:'frozen',running:false,reason:'contract_range_exceeds_expiry',
  config:{symbol:'SHFE.rb2505',end:'2026-10-07'},
  progress:{stage:'frozen',percent:null,current_ns:null,completed_bars:0,fill_count:0,elapsed_seconds:2.6,last_advance_age_seconds:2.6}};
const p=QfResearch.describeState(state);
assert.equal(p.terminal,true);assert.equal(p.progressValue,0);assert.equal(p.showChart,false);
assert.ok(p.notice.includes('SHFE.rb2505')&&p.notice.includes('2026-10-07'));
assert.ok(p.notice.includes('结束')&&!p.notice.includes('已开始'));
assert.ok(!p.progressText.includes('等待数据')&&!p.progressText.includes('剩余时间'));
const finished=QfResearch.describeState({...state,status:'backtest_finished',reason:'historical_replay_completed',progress:{...state.progress,percent:100,completed_bars:20}});
assert.equal(finished.progressValue,100);assert.equal(finished.showChart,true);
for(const status of ['discovering','contracts_ready']){
  const query=QfResearch.describeState({...state,status,running:status==='discovering'});
  assert.equal(query.showProgress,false);assert.equal(query.progressText,'');assert.equal(query.showChart,false);
}
const row={expire_datetime:Date.parse('2025-05-15T07:00:00Z')/1000};
assert.equal(QfResearchForm.contractFit(row,'2026-10-07').eligible,false);
assert.equal(QfResearchForm.contractFit(row,'2025-05-15').eligible,true);
assert.equal(QfResearchForm.contractFit({},'2025-05-15').eligible,true);
assert.equal(QfResearchForm.contractFit({expire_datetime:null},'2025-05-15').expiry,null);
console.log('RESEARCH_TERMINAL_OK');
