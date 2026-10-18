const assert=require('node:assert/strict');
require('../qf/web/research-results.js');
assert.equal(globalThis.QfResearchResults.number(null),'—');
assert.equal(globalThis.QfResearchResults.number('1000'),'1,000');
assert.equal(globalThis.QfResearchResults.precision('minute'),'分钟近似（流程验证）');
const events=[{kind:'fill',payload:{fill_keys:['exit-key']},risk:{initial_r:'1000',exit_reason:'stair_stop'}},
 {kind:'reconciled',payload:{},risk:{initial_r:'0',exit_reason:null}}];
assert.equal(globalThis.QfResearchResults.fillEvent(events,'exit-key').risk.exit_reason,'stair_stop');
assert.equal(globalThis.QfResearchResults.fillEvent(events,'exit-key').risk.initial_r,'1000');
assert.equal(globalThis.QfResearchResults.fillEvent(events,'unknown'),undefined);
console.log('RESEARCH_RESULTS_OK');
