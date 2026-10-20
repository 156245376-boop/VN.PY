# 本地快速回测引擎与数据缓存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先保存选定范围的真实历史数据，再用本机数组和内存状态机完成快速研究回测，并用少量TqSdk原版回放验证结果一致性。

**Architecture:** 使用本机SQLite保存实际合约数据、历史主力映射和覆盖证据；本地引擎一次加载范围数据后在内存中计算信号并顺序推进交易，不再在逐柱循环中调用`wait_update`或写大型账户快照。现有TqSdk执行器保留为`tqsdk_validation`，通过独立一致性报告与`local_research`结果比较。

**Tech Stack:** Python 3.13.11、NumPy、pandas、SQLite、TqSdk 3.10.2、现有任务池与WebView2；首版不新增框架或CUDA依赖。

**Spec:** `docs/superpowers/specs/2026-10-20-local-fast-research-workbench-design.md`

## Global Constraints

- 本地数据必须区分实际合约原始价、历史主力映射和连续信号调整价。
- 信号只使用已完成柱；不能用未来数据或当前合约替换历史合约。
- 数据权限、交易日历、历史主力、合约规格或覆盖不足时停止。
- `DataDownloader`是权限门控功能；权限不足必须显示，不绕过。
- 本地顺序执行保持开仓、成交、止损、反手、换月和资金因果关系。
- 分钟近似不能伪造同柱止损/止盈先后；必须使用明确保守规则或标记不确定。
- 本地和TqSdk结果均带独立`engine_kind`，不能混用同一完成状态。
- CUDA只在GPU策略执行器存在且通过一致性测试后启用，不能自动从CUDA静默回退CPU。
- 凭证不进入数据缓存、结果、性能报告或任务计划。
- 每项交付先TDD，再运行相关回归；最终运行`tools/check.ps1`。

---

### Task 1: 数据请求、权限与覆盖契约

**Files:**
- Create: `qf/data_catalog.py`
- Create: `tests/test_data_catalog.py`

**Interfaces:**
- Produces:
  - `DataRequest(continuous,symbol,bar_seconds,start,end,precision)`
  - `DataKey.from_request(request)->str`
  - `DataCapability(status,reason,minute_available,tick_available)`
  - `CoverageReport.complete()->bool`

- [ ] **Step 1: 写失败测试**

```python
from datetime import date
from qf.data_catalog import CoverageReport, DataRequest

def test_data_request_key_is_stable_and_rejects_tick_as_minute():
    request=DataRequest("KQ.m@SHFE.rb","SHFE.rb2505",60,
                        date(2025,1,2),date(2025,1,10),"minute")
    assert request.key()==request.key()
    report=CoverageReport(expected_days=7,observed_days=6,issues=[])
    assert not report.complete()
    assert report.missing_days==1
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_data_catalog.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现不可变契约**

数据键至少包含：

```python
key = "|".join((
    request.continuous,
    request.symbol,
    str(request.bar_seconds),
    request.start.isoformat(),
    request.end.isoformat(),
    request.precision,
))
```

`CoverageReport`校验日期不重复不回退、观测日属于预期交易日、发现问题时`complete()`返回False。

- [ ] **Step 4: 验证边界**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_data_catalog.py -q`

Expected: PASS；拒绝错误精度、倒序日期、重复交易日和非实际合约。

- [ ] **Step 5: 提交**

```powershell
git add qf/data_catalog.py tests/test_data_catalog.py
git commit -m "feat: define historical data request and coverage contracts"
```

### Task 2: 历史数据SQLite存储

**Files:**
- Create: `qf/history_store.py`
- Create: `tests/test_history_store.py`

**Interfaces:**
- Produces:
  - `HistoryStore(root)`
  - `create_dataset(request,source,capability)->dataset_id`
  - `write_bars(dataset_id,rows)->int`
  - `write_mapping(dataset_id,rows)->int`
  - `coverage(dataset_id)->CoverageReport`
  - `load_bars(dataset_id,*,symbol=None)->pandas.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
def test_bars_are_deduplicated_and_group_read_is_ordered(tmp_path):
    store=HistoryStore(tmp_path)
    dataset=store.create_dataset(request(),"fixture",capability())
    rows=[bar(100,1),bar(160,2),bar(100,1)]
    assert store.write_bars(dataset,rows)==2
    frame=store.load_bars(dataset,symbol="SHFE.rb2505")
    assert frame.time_ns.tolist()==[100,160]
    assert frame.close.tolist()==[1,2]
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_history_store.py -q`

Expected: FAIL，`HistoryStore`不存在。

- [ ] **Step 3: 实现数据库**

表固定为：

```sql
data_sets(dataset_id TEXT PRIMARY KEY,request_json TEXT,source TEXT,
          capability_json TEXT,status TEXT,sha256 TEXT)
instruments(symbol TEXT PRIMARY KEY,data TEXT)
bars(symbol TEXT,duration INTEGER,time_ns INTEGER,
     open REAL,high REAL,low REAL,close REAL,volume REAL,close_oi REAL,
     PRIMARY KEY(symbol,duration,time_ns))
main_changes(time_ns INTEGER,old_symbol TEXT,new_symbol TEXT,
             offset TEXT,reference_ns INTEGER,PRIMARY KEY(time_ns,new_symbol))
coverage(dataset_id TEXT,issue TEXT,data TEXT,
         PRIMARY KEY(dataset_id,issue))
```

批量写入使用单事务和`executemany`；重复键必须逐字段一致，否则回滚并报告冲突。

- [ ] **Step 4: 验证批量读取和损坏拒绝**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_history_store.py -q`

Expected: PASS；重复数据不增加行，冲突数据不覆盖原值。

- [ ] **Step 5: 提交**

```powershell
git add qf/history_store.py tests/test_history_store.py
git commit -m "feat: add normalized historical data store"
```

### Task 3: TqSdk数据能力探测与增量获取

**Files:**
- Create: `qf/data_acquisition.py`
- Create: `tests/test_data_acquisition.py`
- Modify: `qf/workbench.py`
- Modify: `qf/research_jobs_bridge.py`

**Interfaces:**
- Produces:
  - `HistoryProvider`协议：`probe(request)->DataCapability`、
    `download(request,temp_dir,progress,cancel)->list[dict]`
  - `TqSdkDownloadProvider(api_factory)`
  - `prepare_dataset(provider,store,request,progress,cancel)->{dataset_id,status}`

- [ ] **Step 1: 写失败测试**

```python
def test_permission_denied_does_not_create_complete_dataset(tmp_path):
    provider=DeniedProvider("需要tq_dl权限")
    result=prepare_dataset(provider,HistoryStore(tmp_path),request(),
                           lambda p:None,lambda:False)
    assert result["status"]=="permission_required"
    assert result["dataset_id"] is None
    assert "tq_dl" in result["reason"]
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_data_acquisition.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现官方下载适配**

`TqSdkDownloadProvider`仅通过官方`DataDownloader`或已核实权限的数据接口取数。
下载到临时CSV后执行：

1. 解析并规范化实际合约字段；
2. 检查时间、OHLC、重复和交易日覆盖；
3. 写入`HistoryStore`；
4. 保存来源和权限证据；
5. 删除临时文件。

`TqBacktest`不用于任意长区间导出；它产生的柱缓存单独标为`tqsdk_observed`。

- [ ] **Step 4: 验证取消和断点**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_data_acquisition.py -q
```

Expected: PASS；取消后数据集为`cancelled`，不得标为完整。

- [ ] **Step 5: 提交**

```powershell
git add qf/data_acquisition.py qf/workbench.py qf/research_jobs_bridge.py tests/test_data_acquisition.py
git commit -m "feat: add permission-aware historical data acquisition"
```

### Task 4: 连续数据与双均线信号数组

**Files:**
- Create: `qf/local_data.py`
- Create: `qf/local_signals.py`
- Create: `tests/test_local_signals.py`

- [ ] **Step 1: 写失败测试**

```python
def test_signal_uses_only_completed_previous_bars():
    bars=frame(close=[100,99,98,101,103],completed=[1,1,1,1,0])
    signals=ma_cross_signals(bars,fast=2,slow=3)
    assert signals[-1]["bar_index"]==3
    assert signals[-1]["direction"]==1
    assert 4 not in {item["bar_index"] for item in signals}
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_local_signals.py -q`

Expected: FAIL，函数不存在。

- [ ] **Step 3: 实现数据加载和信号**

`local_data.load_continuous_frame(store,dataset_id)`：

- 一次加载实际柱和映射；
- 用与`SignalSeries`一致的因果偏移生成调整价；
- 返回NumPy数组及每根柱的实际合约、完成时间和映射代号；
- 不重新计算或改写已保存的映射偏移。

`local_signals.ma_cross_signals`：

- 仅读取`completed=True`的前一根；
- 用向量化滑动均值生成候选；
- 用显式比较生成方向和信号时间；
- 预热不足不产生信号。

- [ ] **Step 4: 验证与现有实现一致**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_local_signals.py tests\test_continuous_series.py -q
```

Expected: PASS；同一柱子窗口的信号方向、完成时间和调整价一致。

- [ ] **Step 5: 提交**

```powershell
git add qf/local_data.py qf/local_signals.py tests/test_local_signals.py
git commit -m "feat: load causal local bars and vectorized signals"
```

### Task 5: 本地顺序执行器和结果账本

**Files:**
- Create: `qf/local_backtest.py`
- Create: `tests/test_local_backtest.py`
- Modify: `qf/research_config.py`

**Interfaces:**
- Produces:
  - `LocalBacktestEngine.run(dataset,config,progress=None,cancel=None)->LocalRunResult`
  - `LocalRunResult.fingerprint()->dict`
  - `engine_kind="local_research"`

- [ ] **Step 1: 写失败测试**

```python
def test_long_signal_opens_next_executable_bar_and_applies_fee():
    result=LocalBacktestEngine().run(dataset(),config(),progress=None,cancel=lambda:False)
    assert result.status=="backtest_finished"
    assert result.fills[0]["signal_bar"]==2
    assert result.fills[0]["execution_bar"]==3
    assert result.fills[0]["direction"]=="BUY"
    assert result.fees=="2"
    assert result.closed_trade_count>=1
```

- [ ] **Step 2: 运行并验证失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_local_backtest.py -q`

Expected: FAIL，引擎不存在。

- [ ] **Step 3: 实现内存状态机**

首版支持：

- 下一根可执行柱入场规则；
- 固定手数或风险预算定仓；
- 当前确认拐点初始止损；
- 1R/2R阶梯和终点止盈；
- 多空反向先平后开；
- 手续费、保证金和权益；
- 历史主力换月；
- 分钟OHLC下的明确成交假设。

分钟内止损与止盈同时落在同一根柱时使用保守顺序：先触发保护，标记
`intrabar_resolution="conservative_stop_first"`。Tick数据存在时按Tick顺序执行。

- [ ] **Step 4: 验证关键边界**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_local_backtest.py -q
```

Expected: PASS；资金不足、最小手数、反手、部分成交、换月、终点持仓和中途取消均有断言。

- [ ] **Step 5: 提交**

```powershell
git add qf/local_backtest.py qf/research_config.py tests/test_local_backtest.py
git commit -m "feat: run stateful research backtests from local data"
```

### Task 6: 本地结果持久化与交易账本

**Files:**
- Create: `qf/local_results.py`
- Create: `tests/test_local_results.py`
- Modify: `qf/research_results.py`
- Modify: `qf/trade_ledger.py`

- [ ] **Step 1: 写失败测试**

```python
def test_local_result_keeps_engine_identity_and_trade_fees(tmp_path):
    result=LocalBacktestEngine().run(dataset(),config(),progress=None,cancel=lambda:False)
    run_id=save_local_result(tmp_path,result,source_fingerprint())
    summary=summarize_run(tmp_path,run_id)
    assert summary["engine_kind"]=="local_research"
    assert summary["cost_reconciled"] is True
    assert summary["trade_ledger"]["fee_total"]==summary["commission"]
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_local_results.py -q`

Expected: FAIL，持久化函数不存在。

- [ ] **Step 3: 实现批量保存**

保存：

- 实验公开配置；
- 数据`dataset_id`和覆盖摘要；
- 代码版本、引擎版本、策略版本和计算后端；
- 成交、订单用途、逻辑交易、权益采样和风险事件；
- 数据差异说明和分钟近似标记；
- 完整交易CSV、指标CSV和JSON摘要。

结果schema不得与TqSdk结果混读；读器按`engine_kind`选择白名单和完整性算法。

- [ ] **Step 4: 验证账本金额**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_local_results.py tests\test_trade_analytics.py -q
```

Expected: PASS；逐笔费用合计、账户费用、交易净盈亏和结果摘要一致。

- [ ] **Step 5: 提交**

```powershell
git add qf/local_results.py qf/research_results.py qf/trade_ledger.py tests/test_local_results.py
git commit -m "feat: persist local research results and ledger"
```

### Task 7: TqSdk一致性验证

**Files:**
- Create: `qf/backtest_parity.py`
- Create: `tests/test_backtest_parity.py`
- Modify: `qf/research_jobs_bridge.py`
- Modify: `qf/web/research-results.js`

**Interfaces:**
- Produces:
  - `compare_runs(local_run,tqsdk_run)->ParityReport`
  - `ParityReport.status in ("matched","differences","incomplete")`

- [ ] **Step 1: 写失败测试**

```python
def test_parity_compares_signals_fills_fees_and_terminal_equity():
    report=compare_runs(local_fixture(),tqsdk_fixture())
    assert report.status=="matched"
    assert report.signal_difference==0
    assert report.fill_difference==0
    assert report.fee_difference=="0"
    assert report.equity_difference=="0"
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_backtest_parity.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现差异报告**

比较至少包含：

```text
run_id、engine_kind、data_set、signal_fingerprint、fill_fingerprint、
fee_difference、trade_count_difference、open_position_difference、
terminal_equity_difference、first_divergence、tolerance、status
```

真实撮合差异只能通过报告解释，不能修改本地成交去迎合TqSdk。

- [ ] **Step 4: 验证差异可见**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_backtest_parity.py -q
```

Expected: PASS；故意改变一笔费用时状态为`differences`并定位到成交。

- [ ] **Step 5: 提交**

```powershell
git add qf/backtest_parity.py qf/research_jobs_bridge.py qf/web/research-results.js tests/test_backtest_parity.py
git commit -m "feat: compare local research and TqSdk validation runs"
```

### Task 8: CPU并行、数据任务和计算后端UI

**Files:**
- Create: `qf/compute_backend.py`
- Create: `tests/test_compute_backend.py`
- Modify: `qf/backtest_plan.py`
- Modify: `qf/web/research-planner.js`
- Modify: `qf/web/research-form.js`
- Modify: `qf/web/research.js`
- Modify: `qf/web/index.html`

**Interfaces:**
- Produces:
  - `ComputeBackend.catalog()->{cpu:{available:True},cuda:{available:bool,reason:str}}`
  - `BackendRequest(mode,strategy_id,engine_kind)`
  - 计划槽位字段`engine_kind="local_research"|"tqsdk_validation"`和`compute_backend="cpu"|"cuda"`

- [ ] **Step 1: 写失败测试**

```python
def test_cuda_is_rejected_without_gpu_executor():
    catalog=ComputeBackend.catalog()
    assert catalog["cpu"]["available"] is True
    assert catalog["cuda"]["available"] is False
    assert "GPU执行器" in catalog["cuda"]["reason"]
    with pytest.raises(ValueError):
        BackendRequest.validate("cuda","ma_cross","local_research")
```

- [ ] **Step 2: 运行并确认失败**

Run: `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_compute_backend.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现后端能力**

UI显示：

```text
计算后端：CPU（可用）
CUDA：不可用——当前双均线研究引擎没有GPU执行器
```

CPU参数扫描以独立`spawn`worker执行，不能在单任务内部并行改写因果顺序。
CUDA值只有在注册了实际GPU执行器并通过Parity测试后才变为可用。

- [ ] **Step 4: 验证本地与TqSdk任务身份**

Run:

```powershell
node tests\research_planner_node.js
.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests\test_compute_backend.py tests\test_backtest_plan.py -q
```

Expected: PASS；任务卡明确显示“快速研究”或“TqSdk验证”。

- [ ] **Step 5: 提交**

```powershell
git add qf/compute_backend.py qf/backtest_plan.py qf/web/research-planner.js qf/web/research-form.js qf/web/research.js qf/web/index.html tests/test_compute_backend.py
git commit -m "feat: expose honest CPU and CUDA backend capability"
```

### Task 9: 性能基准、真实数据能力验收与文档

**Files:**
- Create: `tests/local_backtest_perf_probe.py`
- Create: `tests/test_local_backtest_performance.py`
- Modify: `docs/research-paper-guide.md`
- Modify: `docs/requirements.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 写固定输入性能探针**

```python
def run_once(rows):
    dataset=fixture_dataset(rows)
    started=time.perf_counter()
    result=LocalBacktestEngine(profile=True).run(
        dataset,config(),progress=None,cancel=lambda:False)
    return {"elapsed":time.perf_counter()-started,
            "profile":result.profile,
            "fingerprint":result.fingerprint()}
```

探针重复3次并输出中位数：数据加载、信号、执行、保存准备、内存峰值。

- [ ] **Step 2: 运行基准**

Run:

```powershell
.\.venv-tqsdk\Scripts\python.exe -B tests\local_backtest_perf_probe.py --rows 8000 --repeat 3
```

Expected: 输出JSON，不预填虚假速度目标；三次交易指纹一致。

- [ ] **Step 3: 跑完整检查**

Run: `.\tools\check.ps1`

Expected: 所有pytest、Ruff、依赖、环境和原生资源检查通过。

- [ ] **Step 4: 用实际账户核对数据能力**

只读核实：

- 免费账户是否能取得目标分钟/Tick范围；
- `DataDownloader`权限状态；
- 历史主力映射和合约规格；
- 先在短区间运行`local_research`和`tqsdk_validation`；
- 任意权限不足都记录为未完成，不切换样本冒充成功。

- [ ] **Step 5: 更新文档并提交**

说明数据目录、权限提示、两种引擎标签、分钟近似、CUDA不可用原因和真实联网验收边界。

```powershell
git add tests/local_backtest_perf_probe.py tests/test_local_backtest_performance.py docs/research-paper-guide.md docs/requirements.md CLAUDE.md
git commit -m "docs: report local engine capabilities and performance"
```

## 自审

- 覆盖：数据请求→Task 1；本机存储→Task 2；权限和获取→Task 3；数据与信号→Task 4；
  执行→Task 5；结果→Task 6；TqSdk对照→Task 7；CPU/CUDA能力→Task 8；性能与真实权限→Task 9。
- 类型：所有结果带`engine_kind`；所有数据读取带`dataset_id`；CUDA无执行器时`available=False`；
  TqSdk验证复用现有结果契约，不改写本地结果。
- 性能公平：先在缓存数据上运行；分阶段报告；分钟近似和保守成交顺序明确；不以关闭覆盖检查换速度。
- 权限边界：`DataDownloader`和Tick范围按账户实际返回；不把`TqBacktest`当作任意导出工具。
