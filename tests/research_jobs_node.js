const assert=require('node:assert/strict');
require('../qf/web/research-jobs.js');
assert.match(QfResearchJobs.describe({config:{name:'A',continuous:'KQ.m@SHFE.rb',bar_seconds:60},
  status:'waiting',progress:{percent:null}}),/等待空闲/);
assert.match(QfResearchJobs.describe({config:{name:'B',continuous:'KQ.m@SHFE.rb',bar_seconds:300},
  status:'backtest_finished',progress:{percent:100}}),/100%/);
console.log('RESEARCH_JOBS_OK');
