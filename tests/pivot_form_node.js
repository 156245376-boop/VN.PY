const assert=require('node:assert/strict');
require('../qf/web/research-form.js');
const f=QfResearchForm.defaults('fixed');
assert.equal(f.schema_version,2);assert.equal(f.strategy_version,2);
assert.equal(f.risk.pivot_left,2);assert.equal(f.risk.pivot_right,2);
assert.equal(f.risk.limit_lots,false);assert.equal(f.risk.limit_margin,false);
assert.equal(f.risk.max_lots,null);assert.equal(f.risk.max_margin_ratio,null);
assert.ok(!('stop_ticks' in f.risk));
console.log('PIVOT_FORM_OK');
