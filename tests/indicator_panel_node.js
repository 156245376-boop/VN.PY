'use strict';const assert=require('node:assert/strict'),cp=require('node:child_process');global.window=global;
require('../qf/web/indicator-state.js');require('../qf/web/indicator-panel.js');
const [meta,defaults]=JSON.parse(cp.execFileSync('.venv-tqsdk/Scripts/python.exe',['-c',
 'import json;from qf.indicator_catalog import indicator_catalog;from qf.indicator_store import default_indicators;print(json.dumps([indicator_catalog(),default_indicators()]))'],{encoding:'utf8'}));
QfIndicatorState.install(meta,defaults);const ma=QfIndicatorState.item('ma');
const changed=QfIndicatorPanel.parameters(ma,{periods:'5, 20，120'});
assert.deepEqual(changed.params.periods,[5,20,120]);assert.deepEqual(ma.params.periods,[5,10,20,60]);
assert.throws(()=>QfIndicatorPanel.parameters(ma,{periods:'5,0'}));
const macd=QfIndicatorState.item('macd');
assert.throws(()=>QfIndicatorPanel.parameters(macd,{short:'30',long:'26',m:'9'}));
console.log('INDICATOR_PANEL_OK');
