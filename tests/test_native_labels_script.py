"""标签初始化没有标题元素时，也必须继续观察后续 DOM。"""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_empty_native_document_remains_observed():
    node = shutil.which("node")
    if not node:
        pytest.skip("原生脚本隔离测试需要 Node.js")
    source = Path(__file__).parents[1] / "qf/web/native-labels.js"
    script = r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const listeners={},parent={postMessage(){}},window={};let observed=false;
const document={body:{},head:{append(){}},querySelector(){return null},
 addEventListener(){},createElement(){return {style:{}}},
 createTreeWalker(){return {nextNode(){return false}}}};
class MutationObserver{disconnect(){observed=false}observe(){observed=true}}
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window,parent,document,
 qfParentOrigin:'http://127.0.0.1:5',MutationObserver,NodeFilter:{SHOW_TEXT:4},
 queueMicrotask,setInterval(){},addEventListener:(name,fn)=>listeners[name]=fn});
assert.doesNotThrow(()=>listeners.DOMContentLoaded());
assert.equal(observed,true,'缺标题后仍需观察晚到的原生内容');
"""
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True,
                            text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
