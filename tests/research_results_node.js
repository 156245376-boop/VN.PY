const assert=require('node:assert/strict');
require('../qf/web/research-results.js');
assert.equal(globalThis.QfResearchResults.number(null),'—');
assert.equal(globalThis.QfResearchResults.number('1000'),'1,000');
assert.equal(globalThis.QfResearchResults.precision('minute'),'分钟近似（流程验证）');
console.log('RESEARCH_RESULTS_OK');
