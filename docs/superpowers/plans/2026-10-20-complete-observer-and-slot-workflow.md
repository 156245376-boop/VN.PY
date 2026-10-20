# 完整研究观察窗、交易分析与回测槽位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有“裸图表外部窗口和临时任务卡”改为完整只读研究观察窗，并把回测启动改为可配置槽位、统一启动、运行中继续新增的工作流。

**Architecture:** 新建只读`ResearchWindowView`，由它提供完整观察页、任务状态和交易账本API，再嵌入现有天勤图表URL。主工作台新增`BacktestPlan`与批量启动接口；页面通过一个统一的`QfResearchPlanner`管理N个草稿槽位、运行任务及新增删除，不再根据并发输入的每次变化直接启动任务。

**Tech Stack:** Python 3.13.11、TqSdk 3.10.2、aiohttp、现有`spawn`任务池、SQLite只读账本、原生JavaScript/WebView2、CSV。

**Spec:** `docs/superpowers/specs/2026-10-20-local-fast-research-workbench-design.md`

## Global Constraints

- 所有用户可见文案使用简体中文，技术标识和日志原文保持原样。
- 不新增实盘入口；快期模拟继续使用现有单账户锁和显式委托确认。
- 凭证不得进入实验、计划文件、任务卡、观察窗URL、日志或CSV。
- 交易明细原始值不可编辑；筛选、统计和导出只生成派生视图。
- 观察窗只读，不能通过其URL修改实验、删除任务或下单。
- 每个观察窗只绑定一个明确`job_id`，不得读取另一任务的状态或账本。
- 运行中任务需先停止再删除；等待中和终态任务可直接删除。
- 批量启动必须先验证全部槽位，任一槽位无效时整批不启动。
- 当前CPU/TqSdk任务继续可用，任何新实现不得破坏已有单任务兼容入口。
- 运行`tools/check.ps1`、Node脚本与真实WebView2烟测后才能宣称完成。

---

### Task 1: 恢复天勤图表右上角工具栏

**Files:**
- Create: `qf/web/native-toolbar.js`
- Modify: `qf/research_chart_assets.py`
- Test: `tests/native_toolbar_browser.js`
- Test: `tests/native_toolbar_smoke.py`

**Interfaces:**
- Consumes: 天勤原生页面里的正文按钮“全屏”“还原”“全屏/还原”。
- Produces: `window.QfNativeToolbar.pin(root=document)->{button,group}`；为按钮添加
  `qf-native-fullscreen`类，为操作组添加`qf-native-top-actions`类。

- [ ] **Step 1: 写浏览器失败测试**

```javascript
const button=[...document.querySelectorAll('button')]
  .find(node=>/全屏|还原/.test(node.textContent));
if(!button)throw Error('未找到全屏按钮');
const chart=document.querySelector('.tq-top-view');
const b=button.getBoundingClientRect(),c=chart.getBoundingClientRect();
if(button.classList.contains('qf-native-fullscreen')===false)
  throw Error('全屏按钮未标记');
if(b.right>c.right-4||b.left<c.left+c.width*.7)
  throw Error('全屏按钮不在右上操作区');
console.log('NATIVE_TOOLBAR_OK');
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -B tests\native_toolbar_smoke.py`

Expected: FAIL，未找到`qf-native-fullscreen`。

- [ ] **Step 3: 实现固定工具栏**

```javascript
(() => {
  'use strict';
  function pin(root=document){
    const button=[...root.querySelectorAll('button,[role="button"]')]
      .find(node=>/全屏|还原/.test((node.textContent||'').trim()));
    if(!button)return null;
    const group=button.parentElement;
    button.classList.add('qf-native-fullscreen');
    group?.classList.add('qf-native-top-actions');
    return {button,group};
  }
  globalThis.QfNativeToolbar={pin};
  if(document.querySelector('.tq-top-view'))setInterval(()=>pin(),500);
})();
```

在`qf/research_chart_assets.py`注入：

```css
.qf-native-top-actions{position:absolute!important;top:8px!important;right:12px!important;
  z-index:12!important;display:flex!important;gap:6px!important}
.qf-native-fullscreen{position:relative!important;flex-shrink:0!important}
```

并在原生页面加载`/native-toolbar.js`。

- [ ] **Step 4: 验证不同宽度**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -B tests\native_toolbar_smoke.py
node tests\native_tools_node.js
```

Expected: `NATIVE_TOOLBAR_OK`，原绘图、缩放和右键测试继续通过。

- [ ] **Step 5: 提交**

```powershell
git add qf/web/native-toolbar.js qf/research_chart_assets.py tests/native_toolbar_browser.js tests/native_toolbar_smoke.py
git commit -m "fix: pin native chart tools to top right"
```

### Task 2: 交易筛选、统计与CSV契约

**Files:**
- Create: `qf/trade_analytics.py`
- Create: `tests/test_trade_analytics.py`

**Interfaces:**
- Consumes: `trade_ledger(db, as_of_ns=None, limit=500)->dict`输出。
- Produces:
  - `normalize_trade_filters(raw:dict)->dict`
  - `filter_trades(ledger:dict, filters:dict)->list[dict]`
  - `trade_statistics(trades:list[dict])->dict`
  - `trade_ledger_csv(trades:list[dict])->str`

- [ ] **Step 1: 写失败测试**

```python
from qf.trade_analytics import filter_trades, normalize_trade_filters, trade_statistics

def test_trade_filters_and_statistics_reconcile():
    ledger={"trades":[
      {"status":"closed","direction":1,"first_symbol":"SHFE.rb2505","exit_reason":"ma_reverse",
       "entry_time_ns":"100","gross_pnl":"700","fee":"30","net_pnl":"670"},
      {"status":"closed","direction":-1,"first_symbol":"DCE.m2509","exit_reason":"initial_stop",
       "entry_time_ns":"200","gross_pnl":"-200","fee":"20","net_pnl":"-220"}]}
    filters=normalize_trade_filters({"direction":1,"status":"closed"})
    trades=filter_trades(ledger,filters)
    stats=trade_statistics(trades)
    assert len(trades)==1
    assert stats=={"count":1,"wins":1,"losses":0,"flat":0,"win_rate":"100",
                   "gross_pnl":"700","fee":"30","net_pnl":"670",
                   "average_win":"670","average_loss":"0",
                   "max_win":"670","max_loss":"0","open_count":0}
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_trade_analytics.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现纯函数**

```python
def normalize_trade_filters(raw):
    direction=raw.get("direction")
    if direction not in (None,"","all",1,-1):
        raise ValueError("交易方向无效")
    status=raw.get("status")
    if status not in (None,"","all","open","closed"):
        raise ValueError("交易状态无效")
    return {"direction":direction,"status":status,
            "symbol":raw.get("symbol") or None,
            "reason":raw.get("reason") or None,
            "start":raw.get("start") or None,
            "end":raw.get("end") or None}
```

`filter_trades`按条目字段筛选；`trade_statistics`使用`Decimal`汇总；`trade_ledger_csv`
使用UTF-8-SIG可读表头和与表格相同的列。

- [ ] **Step 4: 验证CSV金额**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_trade_analytics.py -q`

Expected: PASS；CSV逐笔净盈亏之和等于统计`net_pnl`。

- [ ] **Step 5: 提交**

```powershell
git add qf/trade_analytics.py tests/test_trade_analytics.py
git commit -m "feat: add trade ledger filtering and statistics"
```

### Task 3: 完整只读观察窗服务

**Files:**
- Create: `qf/research_window.py`
- Create: `tests/test_research_window.py`
- Modify: `qf/research_jobs_bridge.py`
- Modify: `qf/workbench.py`
- Test: `tests/test_research_jobs_bridge.py`

**Interfaces:**
- Consumes: `state_provider()->dict`、`ledger_provider(filters:dict)->dict`、
  `chart_provider()->str`。
- Produces: `ResearchWindowView(job_id,state_provider,ledger_provider,chart_provider)`
  和`open()->str`；桥接方法
  `open_research_window(job_id)->{ok,url,job_id,reason}`。

- [ ] **Step 1: 写失败测试**

```python
import asyncio
from aiohttp.test_utils import TestClient, TestServer

def test_window_state_and_ledger_are_job_bound():
    async def exercise():
        state_calls=[]
        view=ResearchWindowView(
            "a"*32,
            lambda: state_calls.append(1) or {
                "job_id":"a"*32,"status":"active","progress":{"percent":12}},
            lambda filters: {"available":True,"trades":[],"fills":[]},
            lambda: "http://127.0.0.1:45678/chart")
        client=TestClient(TestServer(view.app()))
        await client.start_server()
        try:
            packet=await (await client.get("/state")).json()
            assert packet["job_id"]=="a"*32
            assert packet["progress"]["percent"]==12
            assert packet["chart_url"]=="http://127.0.0.1:45678/chart"
        finally:
            await client.close()
    asyncio.run(exercise())
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_window.py -q`

Expected: FAIL，`qf.research_window`不存在。

- [ ] **Step 3: 实现观察窗服务器**

服务器端点固定为：

```text
GET /                 完整观察页
GET /state            脱敏job状态、progress、account、risk、chart_url
GET /ledger           同一job的交易账本
GET /ledger.csv       当前筛选CSV
GET /assets/*         本地viewer脚本和样式
```

`ResearchJobsBridge`为每个`job_id`保存一个观察窗服务；运行任务使用
`LiveResearchView.open()`，完成或停止任务使用`ReplayView.open(run_id)`。删除任务时关闭对应服务。

- [ ] **Step 4: 验证路由和隔离**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_research_window.py tests\test_research_jobs_bridge.py -q
```

Expected: PASS；未知任务返回404或明确错误，不能读取其他job。

- [ ] **Step 5: 提交**

```powershell
git add qf/research_window.py qf/research_jobs_bridge.py qf/workbench.py tests/test_research_window.py tests/test_research_jobs_bridge.py
git commit -m "feat: serve complete job-bound research windows"
```

### Task 4: 观察窗前端、交易筛选与导出

**Files:**
- Create: `qf/web/research-window.html`
- Create: `qf/web/research-window.js`
- Create: `qf/web/research-window.css`
- Create: `tests/research_window_browser.js`
- Create: `tests/research_window_smoke.py`
- Modify: `qf/research_window.py`

**Interfaces:**
- Consumes: `/state`、`/ledger`、`/ledger.csv`。
- Produces: 无需桥接的只读DOM；筛选控件`[data-ledger-filter]`、统计容器
  `#ledger-stats`、CSV按钮`#export-filtered`。

- [ ] **Step 1: 写浏览器失败测试**

```javascript
const assert=(v,m)=>{if(!v)throw Error(m)};
await wait(()=>document.querySelector('#job-progress')?.textContent.includes('37%'),'进度');
const frame=document.querySelector('#research-chart');
assert(frame.src.startsWith('http://127.0.0.1:'),'图表未绑定');
document.querySelector('[data-view=ledger]').click();
await wait(()=>document.querySelectorAll('#ledger-table tbody tr').length===1,'交易行');
assert(document.querySelector('#ledger-stats').textContent.includes('669.58'),'统计');
assert(document.querySelector('#export-filtered'),'无CSV按钮');
console.log('RESEARCH_WINDOW_OK');
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -B tests\research_window_smoke.py`

Expected: FAIL，观察页或控件不存在。

- [ ] **Step 3: 实现页面**

页面结构固定包含：

```html
<header><h1 id="job-title"></h1><span id="job-progress"></span></header>
<iframe id="research-chart" title="任务K线"></iframe>
<section id="account"></section>
<nav><button data-view="ledger">交易明细</button><button data-view="fills">成交记录</button></nav>
<form id="ledger-filters">
  <input data-ledger-filter="start" type="date">
  <input data-ledger-filter="end" type="date">
  <select data-ledger-filter="direction"><option value="">全部</option><option value="1">多</option><option value="-1">空</option></select>
  <select data-ledger-filter="status"><option value="">全部</option><option value="open">持仓中</option><option value="closed">已平仓</option></select>
  <input data-ledger-filter="reason" placeholder="退出原因">
</form>
<div id="ledger-stats"></div>
<div class="research-window-table"><table id="ledger-table"><thead></thead><tbody></tbody></table></div>
<button id="export-filtered">导出当前筛选CSV</button>
```

页面每秒轮询`/state`；只有任务、成交数或账本关键值变化时刷新表格，保留筛选和滚动位置。

- [ ] **Step 4: 验证浏览器流程**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -B tests\research_window_smoke.py
node --check qf\web\research-window.js
```

Expected: `RESEARCH_WINDOW_OK`。

- [ ] **Step 5: 提交**

```powershell
git add qf/web/research-window.html qf/web/research-window.js qf/web/research-window.css qf/research_window.py tests/research_window_browser.js tests/research_window_smoke.py
git commit -m "feat: add complete independent research viewer"
```

### Task 5: 批量回测计划与原子校验

**Files:**
- Create: `qf/backtest_plan.py`
- Create: `tests/test_backtest_plan.py`
- Modify: `qf/research_jobs.py`
- Modify: `qf/research_jobs_bridge.py`
- Modify: `qf/workbench.py`

**Interfaces:**
- Consumes: 已保存实验修订`{experiment_id,revision}`、并发数`capacity`、
  `include_fee_stress:bool`。
- Produces:
  - `BacktestPlan.validate(raw)->BacktestPlan`
  - `ResearchJobs.submit_many(configs,credentials,experiment_refs,request_id)->{job_ids}`
  - `ResearchJobsBridge.start_backtest_batch(plan,request_id)->{ok,job_ids,errors}`

- [ ] **Step 1: 写失败测试**

```python
def test_batch_validation_is_all_or_nothing(tmp_path):
    plan=BacktestPlan.validate({"capacity":2,"slots":[
      {"experiment_id":"a"*32,"revision":1,"include_fee_stress":False},
      {"experiment_id":"b"*32,"revision":1,"include_fee_stress":True}]})
    assert len(plan.slots)==2 and plan.capacity==2
    with pytest.raises(ValueError):
        BacktestPlan.validate({"capacity":3,"slots":[
          {"experiment_id":"a"*32,"revision":1,"include_fee_stress":False}]})
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_backtest_plan.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现计划与批量提交**

计划严格限制`1 <= capacity <= 4`和`1 <= len(slots) <= 4`。开始前先读取并验证全部实验，
再调用`ResearchJobs.submit_many`；`submit_many`先冻结全部任务，任一失败时删除本次已创建任务，
不启动任何worker。

- [ ] **Step 4: 验证批量失败不启动任务**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_backtest_plan.py tests\test_research_jobs.py tests\test_research_jobs_bridge.py -q
```

Expected: PASS；错误槽位有索引，整批`job_ids=[]`。

- [ ] **Step 5: 提交**

```powershell
git add qf/backtest_plan.py qf/research_jobs.py qf/research_jobs_bridge.py qf/workbench.py tests/test_backtest_plan.py tests/test_research_jobs.py tests/test_research_jobs_bridge.py
git commit -m "feat: add atomic backtest batch planning"
```

### Task 6: 槽位配置界面与统一开始

**Files:**
- Create: `qf/web/research-planner.js`
- Create: `tests/research_planner_node.js`
- Modify: `qf/web/research.js`
- Modify: `qf/web/research-form.js`
- Modify: `qf/web/index.html`
- Modify: `qf/web/style.css`
- Modify: `tests/research_jobs_browser.js`

**Interfaces:**
- Consumes: `api.start_backtest_batch(plan,request_id)`、
  `api.list_backtest_jobs()`和实验存储API。
- Produces:
  - `QfResearchPlanner.create(root,api,{onStart,onJob,onNotice})`
  - `.setCapacity(n)`、`.slots()`、`.setSlots(items)`、`.refreshJobs()`、
    `.dispose()`。

- [ ] **Step 1: 写Node失败测试**

```javascript
const planner=QfResearchPlanner.create(root,api,{onStart:async plan=>plan});
planner.setCapacity(2);
assert.equal(planner.slots().length,2);
assert.equal(byText(root,'开始全部回测').disabled,false);
planner.configure(0,{experiment_id:'a'.repeat(32),revision:1,name:'A'});
planner.configure(1,{experiment_id:'b'.repeat(32),revision:1,name:'B'});
assert.deepEqual((await byText(root,'开始全部回测').onclick()).slots.map(x=>x.experiment_id),
  ['a'.repeat(32),'b'.repeat(32)]);
```

- [ ] **Step 2: 运行并验证失败**

Run: `node tests/research_planner_node.js`

Expected: FAIL，`QfResearchPlanner`不存在。

- [ ] **Step 3: 实现槽位组件**

计划区固定结构：

```html
<section id="backtest-plan">
  <label>并发数 <input id="plan-capacity" type="number" min="1" max="4"></label>
  <div id="plan-slots"></div>
  <button id="start-all">开始全部回测</button>
</section>
<section id="running-jobs"></section>
```

每行显示摘要和“配置策略”；点击后展开现有`QfResearchForm`，保存只更新该槽位草稿，
不立即启动。策略编辑区默认折叠。

- [ ] **Step 4: 验证两槽位和一次提交**

Run:

```powershell
node tests\research_planner_node.js
.\.venv-tqsdk\Scripts\python.exe -B tests\research_jobs_workbench_smoke.py
```

Expected: `RESEARCH_PLANNER_OK`、`RESEARCH_JOBS_WORKBENCH_OK`。

- [ ] **Step 5: 提交**

```powershell
git add qf/web/research-planner.js qf/web/research.js qf/web/research-form.js qf/web/index.html qf/web/style.css tests/research_planner_node.js tests/research_jobs_browser.js
git commit -m "feat: configure and start backtests by slot"
```

### Task 7: 运行中添加、排队、停止和删除

**Files:**
- Modify: `qf/web/research-planner.js`
- Modify: `qf/web/research-jobs.js`
- Modify: `qf/research_jobs_bridge.py`
- Modify: `tests/research_planner_node.js`
- Modify: `tests/research_jobs_browser.js`

**Interfaces:**
- Consumes: Task 5批量接口、现有`stop_backtest(job_id)`和`remove_backtest(job_id)`。
- Produces: `planner.addDraft()`、`planner.startAdded()`；任务卡操作不改变容量。

- [ ] **Step 1: 写失败测试**

```javascript
planner.setCapacity(1);
planner.configure(0,{experiment_id:'a'.repeat(32),revision:1,name:'A'});
await byText(root,'开始全部回测').onclick();
planner.addDraft({experiment_id:'b'.repeat(32),revision:1,name:'B'});
assert.equal(planner.slots().length,1,'新增槽位不能偷改并发数');
await byText(root,'开始新增任务').onclick();
assert.deepEqual(submitted.map(item=>item.experiment_id),[ 'b'.repeat(32)]);
```

- [ ] **Step 2: 运行并确认失败**

Run: `node tests/research_planner_node.js`

Expected: FAIL，新增接口未实现。

- [ ] **Step 3: 实现运行中编排**

运行区固定显示：

- `并发上限：N`
- `运行：x / N`
- `等待：y`
- “新增回测任务”
- “开始新增任务”

新增槽位只形成草稿。点击“开始新增任务”按Task 5批量提交；容量已满时任务明确排队。
删除等待/终态任务直接调用`remove_backtest`；运行任务先调用`stop_backtest`，终态后再显示删除。

- [ ] **Step 4: 验证容量1下新增排队**

Run:

```powershell
node tests\research_planner_node.js
.\.venv-tqsdk\Scripts\python.exe -B tests\research_jobs_workbench_smoke.py
node tests\research_jobs_node.js
```

Expected: 三个测试全部通过；添加任务不修改容量输入。

- [ ] **Step 5: 提交**

```powershell
git add qf/web/research-planner.js qf/web/research-jobs.js qf/research_jobs_bridge.py tests/research_planner_node.js tests/research_jobs_browser.js tests/research_jobs_node.js
git commit -m "feat: add running jobs without changing capacity"
```

### Task 8: 完整Windows验收与操作文档

**Files:**
- Modify: `tests/research_jobs_workbench_smoke.py`
- Modify: `tests/research_jobs_browser.js`
- Modify: `tests/research_workbench_smoke.py`
- Modify: `docs/research-paper-guide.md`
- Modify: `docs/requirements.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 扩展真实WebView2烟测**

烟测必须完成：

```text
并发1→配置A→开始→A运行
新增B→并发仍为1→开始新增→B等待
停止A→B开始
打开A完成观察窗→进度/账户/交易统计可见
筛选交易→统计变化→导出CSV
关闭观察窗→主工作台任务不受影响
```

- [ ] **Step 2: 运行全部专项测试**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -B tests\research_jobs_workbench_smoke.py
.\.venv-tqsdk\Scripts\python.exe -B tests\research_window_smoke.py
.\.venv-tqsdk\Scripts\python.exe -B tests\research_workbench_smoke.py
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_backtest_plan.py tests\test_trade_analytics.py tests\test_research_window.py tests\test_research_jobs_bridge.py -q
```

Expected: 全部成功，输出含`RESEARCH_JOBS_WORKBENCH_OK`和`RESEARCH_WINDOW_OK`。

- [ ] **Step 3: 跑完整检查**

Run: `.\tools\check.ps1`

Expected: 所有pytest、Ruff、依赖、环境和原生资源检查通过。

- [ ] **Step 4: 更新文档**

说明槽位启动、并发与计划数区别、运行中新增、完整观察窗、筛选统计、CSV位置，
以及旧任务卡和独立裸图表入口的兼容状态。

- [ ] **Step 5: 提交**

```powershell
git add tests/research_jobs_workbench_smoke.py tests/research_jobs_browser.js tests/research_workbench_smoke.py docs/research-paper-guide.md docs/requirements.md CLAUDE.md
git commit -m "docs: explain complete observer and slot workflow"
```

## 自审

- 覆盖：工具栏→Task 1；观察窗→Tasks 3—4；交易分析→Task 2和4；批量校验→Task 5；
  槽位UI→Task 6；运行中新增→Task 7；真实验收→Task 8。
- 类型：观察窗始终使用`job_id`；统计和CSV共用`filter_trades`；批量提交只调用
  `start_backtest_batch`；新增任务不修改`capacity`。
- 安全：观察窗和导出均只读；计划中不含凭证；URL和API超时、任务不存在、运行中删除均有明确失败。
