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
const warmupProgress={stage:'warmup',current_ns:'1733292540000000000',trading_start_ns:'1735747200000000000',
  warmup_percent:6,percent:0,completed_bars:640,fill_count:0,elapsed_seconds:94,last_advance_age_seconds:0};
const warmup=QfResearch.describeState({status:'active',mode:'backtest',config:{start:'2025-01-02'},progress:warmupProgress});
assert.equal(warmup.progressValue,6);
assert.ok(warmup.progressText.includes('不下单')&&warmup.progressText.includes('2025-01-02'));
assert.ok(warmup.progressText.includes('2024')&&!warmup.progressText.includes('尚未推进'));
assert.ok(warmup.phaseNotice.includes('正式交易')&&warmup.phaseNotice.includes('不下单'));
const prewarmStop=QfResearch.describeState({status:'stopped',reason:'requested_stop',config:{start:'2025-01-02'},
  progress:{...warmupProgress,stage:'stopped'}});
assert.ok(prewarmStop.progressText.includes('尚未开始')&&prewarmStop.progressText.includes('预热'));
assert.ok(prewarmStop.phaseNotice.includes('已停止')&&!prewarmStop.phaseNotice.includes('预热中'));
assert.equal(prewarmStop.progressValue,0);
const active=QfResearch.describeState({status:'active',config:{start:'2025-01-02'},
  progress:{...warmupProgress,stage:'backtesting',warmup_percent:null,percent:12,fill_count:1}});
assert.equal(active.progressValue,12);assert.equal(active.phaseNotice,'');
console.log('RESEARCH_TERMINAL_OK');
