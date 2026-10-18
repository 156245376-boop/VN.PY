# 双均线实验与阶梯保护实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有独立工作台中完成可选参数的双均线回测、阶梯保护、实验比较、成交复盘与显式快期模拟。

**Architecture:** 保留旧固定样例，将新实验作为版本化配置接入。纯信号与纯风险计算共用于回测和模拟，现有Guard/Journal/TargetPosTask承担受限执行和核对；工作台仅通过白名单接口控制后台串行会话。复盘读取本机保存数据并复用锁定SDK图表，不重取行情重建证据。

**Tech Stack:** Windows PowerShell、Python 3.13.11、TqSdk 3.10.2、SQLite、TOML、现有pywebview/WebView2及原生JavaScript；无新增产品依赖。

**Spec:** [已确认设计](../specs/2026-10-18-ma-cross-risk-research-design.md)

## Global Constraints

- 本轮实现单策略、单实际合约、单账户串行运行，不增加实盘入口、多品种组合、批量优化或新闻交易。
- 本次测试：1R推至开仓价向盈利方向1跳；2R推至盈利0.5R；3R直接退出。
- 盈亏和R均指本笔持仓价差毛盈亏；手续费单列，结果同时显示净收益。
- 回测精度首选明确标注的“分钟近似（流程验证）”；可显式选择“Tick（需要核实权限与覆盖）”。不能因Tick不可用而自动改成分钟。
- 现有Config.period仍指旧样例均线长度，不复用为新策略的K线周期。
- 模拟只使用一个TqKq主账户和现有跨进程账户锁；新模拟实验要求整账户空仓且无未结委托。
- 重新启动默认观察；缺少持仓期间风险更新记录、进程异常中断或无法对账时保持冻结。
- 凭证继续由Windows安全保存或内存传递；debug=False；本机结果、市场数据、凭证不进Git。
- 不修改SDK安装文件，不自动升级，不恢复archive，不创建通用策略插件平台或通用交易框架。
- 使用当前codex/research-paper-loop工作区；不杀用户进程；图形验收串行、使用临时目录和合成数据。
- 每个任务先红后绿，提交前检查实际差异；安装只用tools/setup.ps1，最终执行tools/check.ps1。

## Review Focus

1. 用户重复点击启动/修改正在运行的草稿：只能创建一次运行，执行中配置快照不可改变（任务5）。
2. 行情已前进但又收到旧时间报价，或同一时间成交与报价分开发来：不回退保护、不漏新成交、不重复触发退出（任务2、4）。
3. 历史结果文件不完整、旧版本或用户选择了错误run_id：显示明确不可复盘原因，不借当前行情补造结果（任务3、6）。
4. 桥接传入路径穿越、伪造合约/模式及网页脚本文本：不能读取任意文件、发起实盘或作为HTML执行（任务1、5、6）。
5. 有部分仓位时断线或点退出：不宣称已平仓、不反复确认、不无限阻塞窗口，未决状态保留（任务4、5、7）。

## 文件结构与依赖

| 文件 | 单一职责 |
| --- | --- |
| qf/research_config.py、qf/experiment_store.py | 新版本配置校验、TOML不可变修订与复制 |
| qf/ma_cross.py、qf/trade_risk.py | 已完成柱交叉、定仓与阶梯风险状态计算 |
| qf/research_journal.py、qf/research_results.py | 事务记录、结果读取、统计及A/B比较 |
| qf/research_runtime.py | 新实验SDK订阅、运行状态机与执行编排 |
| qf/safety.py、qf/runtime.py | 保留旧默认的受限Guard扩展及共享适配复用 |
| qf/research_session.py | 后台串行实验、停止控制和脱敏输出 |
| qf/replay_view.py、qf/web/native-replay.js | 已存数据的本机原生图表服务及成交/保护覆盖层 |
| qf/workbench.py、qf/window_host.py | 受限研究桥接、图表脚本安装与关闭协同 |
| qf/web/research-form.js、research-results.js、research.js | 表单、结果比较与研究页面生命周期 |
| qf/web/index.html、app.js、style.css | 三个研究导航入口与已有工作台集成 |
| docs/research-paper-guide.md、docs/requirements.md、CLAUDE.md | 点击教程、已实现范围和短地图 |

按任务1→2→3→4→5→6→7执行；同一任务内不并发修改共享文件。后续任务使用以下接口，不更名后让消费者猜。
所有domain数值严格拒绝bool、NaN和Infinity；金额/价格运算在风险模块使用Decimal，公开快照将Decimal序列化为十进制字符串，SDK边界才转float。

### Task 1：可保存、复制且不改旧样例的实验配置

**Files:** 新建qf/research_config.py、qf/experiment_store.py、tests/test_research_config.py、tests/test_experiment_store.py；读取但不放宽qf/config.py。

**Interfaces:**
- ResearchConfig为冻结数据类，字段固定为schema_version=1、strategy_id="ma_cross"、strategy_version=1、name、symbol、continuous、bar_seconds、fast_period、slow_period、start、end、initial_balance、precision、timeout_seconds、execution_timeout_seconds、risk；public()返回白名单dict。
- RiskConfig冻结字段：sizing("fixed"/"risk_budget")、fixed_lots、risk_budget、stop_ticks、max_lots、max_margin_ratio、take_profit_mode("r_multiple"/"amount")、take_profit_value、stairs_enabled、first_trigger_r=1、first_offset_ticks=1、second_trigger_r=2、second_lock_r=0.5。
- validate_research_config(raw: dict) -> ResearchConfig；start/end为ISO日期，bar_seconds取60/300/900/1800/3600/86400，precision取minute/tick；超时5..600秒，max_margin_ratio为(0,1]。
- ExperimentStore(root: Path)：save(config: ResearchConfig, *, experiment_id: str|None=None) -> dict、load(experiment_id: str, revision: int) -> ResearchConfig、list() -> list[dict]、copy(experiment_id: str, revision: int, *, name: str) -> dict。
- 返回引用固定为experiment_id（UUID十六进制）、revision、parent（仅含来源experiment_id/revision或None）；修订不覆盖，写临时文件后原子提交；仅在指定根下读写，不接受网页传路径。

- [ ] **Step 1：写失败测试。** `test_new_config_does_not_change_legacy_period`使用`assert legacy.period == 15`、`assert config.bar_seconds == 300`；`test_config_rejects_unknown_secret_bool_nan_and_invalid_stairs`对password/未知字段、bool手数、非有限金额、fast>=slow及R倍数终点低于第二档使用`with pytest.raises(ValueError)`。`test_copy_is_new_identity_and_revision_is_immutable`保存5/20再复制10/30，使用`assert copied['experiment_id'] != original['experiment_id']`、`assert copied['parent'] == {k: original[k] for k in ('experiment_id', 'revision')}`及`assert store.load(original['experiment_id'], original['revision']).fast_period == 5`；`test_store_rejects_traversal_and_interrupted_write_preserves_previous`覆盖../、绝对路径及模拟写入失败。
- [ ] **Step 2：运行红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_config.py tests/test_experiment_store.py -q`；预期因新模块/接口未实现失败，不能是fixture或环境错误。
- [ ] **Step 3：实现上述接口。** TOML用标准库读取、显式白名单写入，无新增依赖；draft可未填写风险数值，保存可运行修订必须完整验证。金额终点是否使阶梯不可达依赖实际定仓R，在开仓预览/执行时再次拒绝，不把“元”和R直接比较。
- [ ] **Step 4：运行绿测及旧配置回归。** 同上并加入tests/test_research_core.py、tests/test_cli.py；预期全部通过。
- [ ] **Step 5：仅提交本任务文件。** `git add -- qf/research_config.py qf/experiment_store.py tests/test_research_config.py tests/test_experiment_store.py`；`git commit -m "feat: 添加版本化策略实验配置与复制"`。

### Task 2：双均线、定仓和多空对称的阶梯保护

**Files:** 新建qf/ma_cross.py、qf/trade_risk.py、tests/test_ma_cross.py、tests/test_trade_risk.py；复用现有tafunc.ma的口径，不改qf/strategy.py旧信号。

**Interfaces:**
- CrossSignal冻结字段bar_start_ns、completed_ns、direction(-1/1)、fast_previous、slow_previous、fast_current、slow_current。
- completed_cross(rows: list[dict], fast: int, slow: int, *, completed_ns: int) -> CrossSignal|None；rows含形成中最后一柱，datetime为整数ns、close为有效正价格；completed_ns由适配器依据新柱出现时刻给出。
- ContractSpec冻结字段symbol、price_tick、volume_multiple、min_open_lots、lot_step、margin_per_lot、commission_per_lot、cost_source；资金值为Decimal，手数为int。
- SizingDecision冻结字段lots、budget、initial_r、margin、reason；size_order(risk: RiskConfig, spec: ContractSpec, *, available: Decimal, startup_equity: Decimal) -> SizingDecision。
- RiskState冻结字段trade_id、side、quantity、entry_price、initial_r、sealed、stage、stop_price、peak_gross、last_quote_ns、last_fill_ns、exit_reason。初始state由empty_risk() -> RiskState产生。
- apply_entry_fill(state: RiskState, *, side: int, price: Decimal, quantity: int, time_ns: int, risk: RiskConfig, spec: ContractSpec, trade_id: str) -> RiskState；seal_entry(state: RiskState) -> RiskState。
- protect(state: RiskState, *, price: Decimal, time_ns: int, risk: RiskConfig, spec: ContractSpec) -> RiskState；纯函数只产生状态，exit_reason为None/initial_stop/stair_stop/take_profit；同时间价更新可检查保护，time_ns更旧则拒绝行情更新，成交独立处理。

- [ ] **Step 1：写失败测试。** `test_cross_uses_two_completed_windows_not_live_bar`用相等→上穿、相等→下穿及恶意末柱验证±1与不受形成柱影响；`test_warmup_duplicate_time_invalid_price_yields_no_signal`覆盖slow+1已完成预热。定仓测试断言每手300/预算1000→3手/R900/3R2700；不足一手→0，最小2手不可上凑，保证金上限不会随盈利增长。
  `test_long_short_staircases_exact_thresholds`设tick=1、乘数10、2手、止损50跳、E=1000，R=1000；多头1050→`assert state.stop_price == Decimal('1001')`，1100→`assert state.stop_price == Decimal('1025')`，1150→`assert state.exit_reason == 'take_profit'`；空头950→999、900→975、850→退出。`test_gap_rounding_stale_quote_and_same_time_quote`验证跳档、只收紧、半跳取整、旧报价及早于最新成交的报价不抬保护、同时间后到成交不丢；`test_partial_fill_does_not_relax_stop_or_change_sealed_r`验证入场补充成交不放宽，封存后拒绝加仓。
- [ ] **Step 2：运行红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_ma_cross.py tests/test_trade_risk.py -q`；预期缺少新接口的失败。
- [ ] **Step 3：实现纯函数。** 阶梯、初始止损和终点在每次有效报价评估；新保护越过当前价格立即退出；固定金额与R终点择一，按实际R拒绝不可达阶梯。保护取整用Decimal整跳，多头向下/空头向上；所有状态保留真实时间，费用不计入毛R。apply_entry_fill仅允许同方向入场，首次成交即建保护，封存后仅由退出成交减少仓位（任务3处理）。
- [ ] **Step 4：绿测。** 同上并加入tests/test_research_core.py；预期全部通过，现有单均线输出不变。
- [ ] **Step 5：提交。** `git add -- qf/ma_cross.py qf/trade_risk.py tests/test_ma_cross.py tests/test_trade_risk.py`；`git commit -m "feat: 实现双均线信号与阶梯风险计算"`。

### Task 3：成交与风险的事务记录、结果统计和比较

**Files:** 新建qf/research_journal.py、qf/research_results.py、tests/test_research_journal.py、tests/test_research_results.py；最小修改qf/journal.py允许复用连接/schema初始化，不改旧导出语义。

**Interfaces:**
- ResearchJournal(Journal)：commit_update(event_id: str, *, time_ns: int, kind: str, payload: dict, risk_state: RiskState, fills: list[dict], target: int|None=None) -> bool；同一event_id返回False且无副作用，所有写入一个事务。
- research_trade_key(fill: dict) -> str对合约、order_id、SDK trade_id和成交时间的白名单元组产生稳定键，保留原始SDK trade_id作为业务字段；新实验不用裸trade_id跨交易日去重，旧样例格式不改。risk_state.trade_id为本笔持仓周期ID，不等同某一笔成交ID。
- capture_bars(symbol: str, bar_seconds: int, rows: list[dict]) -> None；load_risk() -> RiskState；load_replay(*, offset: int, limit: int) -> dict。数据只含ns字符串、OHLCV/OI、信号、成交、保护和原因；柱以(symbol,周期,时间)去重，完成柱不可被形成柱覆盖。
- close_trade_fills(state: RiskState, fills: list[dict]) -> RiskState在qf/trade_risk.py新增：按相反方向CLOSE/CLOSETODAY减少数量，保持已封存R用于本笔退出记录；最终空仓后记录本笔结束，不将SELL OPEN当平多。
- read_run(root: Path, run_id: str) -> dict、summarize_run(root: Path, run_id: str) -> dict、compare_runs(root: Path, run_ids: list[str]) -> dict位于research_results.py；run_id复用既有正则，schema/字段/数值白名单校验，错误为受限reason。
- 报告字段：status、reason、precision、coverage、gross_pnl、net_pnl、commission、max_drawdown_amount、max_drawdown_pct、fill_count、closed_trade_count、open_position；权益balance已含手续费时净收益直接balance-initial，毛收益=净收益+commission，禁止重复扣费。比较返回items、config_differences、comparability_warnings。

- [ ] **Step 1：写失败测试。** `test_fill_risk_and_exit_intent_commit_atomically`在事务中注入写失败，使用`assert journal.expected_position() == 0`、`assert journal.load_risk() == before`断言全回滚；重复成交key不同event_id也不增加仓位，原始trade_id相同但不同交易日的有效成交均保留。`test_two_protection_events_in_one_minute_are_retained`断言1R、2R同一分钟分别记录。`test_realized_trade_count_and_open_position_are_distinct`覆盖部分平仓/末尾持仓；权益[100000,110000,99000]使用`assert summary['max_drawdown_amount'] == '11000'`、`assert summary['max_drawdown_pct'] == '10'`，费用只计一次。`test_missing_old_schema_or_foreign_run_never_reads_live_market`断言无文件、未知版本、错误run_id明确失败；`test_compare_exposes_precision_and_cost_differences`断言A/B与双费类别分开。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_journal.py tests/test_research_results.py -q`；预期接口尚未实现失败。
- [ ] **Step 3：实现接口和增量schema。** 新增risk_events、research_bars、research_run状态，不把quote风控塞进旧signals主键。处理成交时先验证ownership和去重，reduce实际仓位后在同一事务提交；跨平仓成交保留entry锚点和初始R，所有业务事件是白名单。比较最多选两个run_id，关闭后只从本机记录读取，不连接SDK补数据。
- [ ] **Step 4：绿测。** 同上加入tests/test_runtime_safety.py；预期旧Journal/Guard去重及恢复测试继续通过。
- [ ] **Step 5：提交。** `git add -- qf/research_journal.py qf/research_results.py qf/journal.py qf/trade_risk.py tests/test_research_journal.py tests/test_research_results.py`；`git commit -m "feat: 持久记录策略风险与实验比较结果"`。

### Task 4：受限多空执行与真实SDK事件顺序

**Files:** 新建qf/research_runtime.py、tests/test_research_runtime.py、tests/test_research_execution.py；修改qf/safety.py、qf/runtime.py、tests/test_real_sdk_boundary.py；复用tests/test_sdk_loop.py的替身模式但新建可控行情/成交夹具。

**Interfaces:**
- ExecutionScope冻结数据类位于safety.py，字段max_lots、allow_short；Guard(journal, symbol, *, scope: ExecutionScope|None=None, fill_handler: Callable[[dict], None]|None=None)。None保留旧long-only/1手默认，研究运行显式传scope，fill_handler将任务3事务作为唯一成交消费入口。
- discover_contracts(sdk, credentials: tuple[str,str], *, continuous: str, start: date, end: date, timeout: int) -> list[dict]：只读临时会话，返回白名单实际合约与覆盖，不保存凭证，含历史已到期合约；结束必须close。
- execute_research(mode: str, config: ResearchConfig, root: Path, credentials: tuple[str,str], *, sdk=None, activate=False, resume: str|None=None, fee_multiplier=1, stop_requested: Callable[[],bool], flatten_requested: Callable[[],bool], progress: Callable|None=None) -> dict；mode仅backtest/paper。
- 输出包含run_id、status、reason及任务3摘要引用；默认只跑一次基准，双费由调用端作为独立关联实验启动，旧runtime.execute仍默认原两轮行为。

- [ ] **Step 1：写失败测试。** `test_legacy_guard_stays_one_lot_long_only`保留旧拒绝；`test_scoped_guard_counts_pending_open_volume_and_net_short`覆盖多空手数、在途开仓和双向仓；固定target=3不能每次发3手累加超限。`test_risk_runs_on_quote_without_new_bar`同一分钟先1R再2R并回撤，断言退出只一次。`test_partial_entry_stop_cancels_then_reconciles_late_fill`模拟2/3手成交、触发、撤单期间再成交1手，断言最终退出3手且无反向开仓。`test_reverse_waits_for_flat_and_no_orders`断言先target0、确认空仓后才负目标。
  `test_tick_denied_does_not_change_precision_contract_or_account`使用`assert result['status'] == 'failed'`且`assert subscriptions == [('tick', config.symbol)]`核实无降级；`test_minute_subscription_exists_with_hourly_signal`断言一分钟报价+小时信号独立。`test_resume_missing_risk_external_order_disconnect_and_expiry_freeze`覆盖既有边界；`test_close_unconfirmed_does_not_report_flat`断言未决暴露保留。`test_provenance_hash_includes_research_frontend`在临时根修改research.js后断言`assert before['source_sha256'] != after['source_sha256']`。
- [ ] **Step 2：红测并核实SDK。** 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_runtime.py tests/test_research_execution.py -q`预期失败；只读检查本机get_tick_serial、query_quotes、TargetPosTask.cancel/is_finished、最小开仓支持、已完成柱时间/交易日边界。禁止调用真实TqApi进行离线探测。
- [ ] **Step 3：实现运行编排。** 复用tracked_api、provenance、连接/超时核对、PaperLock；先消费所有新成交并提交风险，再核对仓位/挂单，再处理行情保护，最后处理新完成柱。SDK报单入口再次核对Guard；先持久化目标，后set_target_volume。部分入场触发退出时cancel旧任务、等确认、重核在途成交，旧任务结束后才创建退出任务，始终只有一个活动任务；不是cancel即平仓。
  新TargetPosTask使用offset_priority="今,昨,开"保证今仓、昨仓、开仓顺序等待，避免同轮拆分平仓撞上单挂单保护；tests/test_research_execution.py用今仓1手/昨仓1手验证完整退出。最小开仓参数按本机support_open_min_volume能力显式核实和传入，不能忽略构造失败或改用手工报单。
  新阶段明确flat/entering/holding/exiting/frozen/stopped，退出状态只允许减仓，实际空仓且无挂单才结束。记录trigger完成时刻，防止旧交叉重开；等待反向开仓期间方向以最新交叉为准。临近到期沿用旧规则；主力变化只冻结新目标，不自动换月。断线后停止继续报单，不声称离线保护仍有效。
  分钟模式显式订60秒报价来源，信号周期独立；Tick模式显式订Tick并核实返回时间和权限。数据不覆盖/坏序列明确失败。回测起止使用TqBacktest交易日边界及预热，禁止界外委托；期末剩仓只估值不造平仓。provenance增加qf/web递归源码清单及新实验配置版本，不扫描凭证、本机数据或虚拟环境。停机不需无限等待，用execution_timeout_seconds结束等待并保留frozen原因；恢复须同日、干净停止、账户绑定、代码/配置和风险状态全核对，无待应用意图。
- [ ] **Step 4：绿测及真实协程边界。** 同上加入tests/test_real_sdk_boundary.py、tests/test_sdk_loop.py、tests/test_runtime_safety.py；离线真实InsertOrderTask验证BUY/SELL OPEN与CLOSE/CLOSETODAY、位置参数和on_fill事务路径，所有测试不连账户；预期全通过。
- [ ] **Step 5：提交。** `git add -- qf/research_runtime.py qf/safety.py qf/runtime.py tests/test_research_runtime.py tests/test_research_execution.py tests/test_real_sdk_boundary.py`；`git commit -m "feat: 接入多空回测与受限模拟阶梯执行"`。

### Task 5：工作台实验表单、后台会话与模拟控制

**Files:** 新建qf/research_session.py、qf/web/research-form.js、qf/web/research.js、tests/test_research_session.py、tests/test_research_bridge.py、tests/research_form_node.js、tests/test_research_ui.py；修改qf/workbench.py、qf/window_host.py、qf/web/index.html、qf/web/app.js、qf/web/style.css。

**Interfaces:**
- ResearchSession(root: Path, *, execute_fn=None)：start(mode: str, config: ResearchConfig, credentials: tuple[str,str], *, activate=False, resume: str|None=None, experiment_ref: dict) -> dict、stop(*, flatten=False) -> None、snapshot() -> dict、close() -> bool。唯一后台线程负责SDK与SQLite；主线程只用队列/事件，snapshot无SDK引用。
- WorkbenchBridge新增get_experiments()、save_experiment(raw, experiment_id=None)、copy_experiment(experiment_id, revision, name)、get_research_contracts(continuous, start, end)、start_research(experiment_id, revision, mode, activate=False, resume=None)、stop_research(flatten=False)、get_research_state()；返回均为白名单dict。合约查询也占用研究工作队列，运行中不得并发创建查询会话。
- 页面QfResearchForm.create(root, options)返回read()/render(config)/setRunning(bool)/dispose()；QfResearch.create(root, api)返回show(view)/prepareExit()/dispose()。不从行情轮询重复重建研究表单。
- 研究运行读取已有Windows凭证或当前内存凭证，不将已保存密码发回网页，不依靠点击启动自动连接/激活模拟。

- [ ] **Step 1：写失败测试。** `test_double_start_and_draft_edit_cannot_mutate_run`用阻塞execute_fn验证`assert len(calls) == 1`、`assert calls[0].config == original_config`；`test_bridge_rejects_live_traversal_foreign_contract_and_secret_fields`断言仅允许选定目录/合约、backtest/paper及安全ID。`test_saved_login_is_not_returned_and_paper_requires_activate`使用`assert password not in json.dumps(snapshot)`，默认观察；`test_close_with_pending_position_finishes_without_claiming_flat`断言一次关闭确认、后台超时后可退出并保留frozen。Node测试断言中文标签、风险输入切换、实际R预览、2倍费用可选、三个独立导航、已保存配置加载不启动。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_session.py tests/test_research_bridge.py tests/test_research_ui.py -q`；test_research_ui.py复用现有Node查找/执行方式跑research_form_node.js，预期缺少研究接口失败。
- [ ] **Step 3：实现接口与页面。** 保存按钮只保存配置；回测只创建选定修订的run；模拟明确显示TqKq、服务端权益、观察/允许委托状态，启动委托前用户需明确确认。提供停止与“平仓并停止”，关闭确认文字包含仓位与保护停止影响。旧研究按钮仍可用，旧研究与本窗口通过同一PaperLock互斥。
  报价单位、跳数对应金额、实际R和止盈预览来源必须可见，缺参数显示待核实；服务端发现不可信价格/成本再次拒绝，不能只信浏览器校验。stop/close在后台等待，页面退出后停止研究轮询；Worker迟到消息带run_id/revision，不能覆写另一个实验。研究失败不清空行情图或已完成结果。
- [ ] **Step 4：绿测及已有关闭回归。** 同上加入tests/test_workbench.py、tests/test_window_host.py、tests/test_market_shutdown.py；预期全通过。真实WebView验收留任务7串行运行。
- [ ] **Step 5：提交。** 仅git add上述Files中本任务实际修改文件；`git commit -m "feat: 添加双均线实验表单与模拟运行控制"`。

### Task 6：成交复盘、保护线、结果比较与离线重开

**Files:** 新建qf/replay_view.py、qf/web/native-replay.js、qf/web/research-results.js、tests/test_replay_view.py、tests/replay_render_node.js、tests/research_results_node.js；修改qf/workbench.py、qf/window_host.py、qf/web/research.js、qf/web/index.html、tests/test_research_ui.py。

**Interfaces:**
- ReplayView(root: Path)：open(run_id: str) -> str、close() -> None；本机127.0.0.1端口服务只读取已验证run并复用3.10.2原生web资源/klines协议，不构造TqApi、不含认证和交易端点。
- WorkbenchBridge新增list_research_runs()、get_research_result(run_id)、compare_research_runs(run_ids)、open_research_replay(run_id)；后者返回ok/url/run_id/revision，URL使用现有本机白名单。
- QfNativeReplay.attach(chart, options)返回apply(payload)/focusFill(fill_id)/dispose()；payload固定run_id、revision、symbol、bar_seconds、bars、signals、fills、risk_events、coverage、precision，ns为字符串。只接受同run_id/revision且来源匹配的消息。
- QfResearchResults.create(root, api)返回render(summary)/compare(payload)/dispose()；成交点击调用focusFill，按真实成交时间定位所属K线并显示独立价格/成交量/方向/决策原因，不按记录序号猜日期。

- [ ] **Step 1：写失败测试。** `test_replay_opens_without_sdk_or_credentials`使用合成已存结果，用`assert url.startswith('http://127.0.0.1:')`及`api_constructor.assert_not_called()`证明无会话。`test_replay_rejects_path_traversal_old_schema_and_missing_bars`验证白名单和明确失败。Node断言两均线、成交箭头和保护分段共享同一真实坐标；`test_stale_replay_message_and_script_names_do_not_execute`验证旧run消息丢弃，名称用textContent显示。断线区间没有虚拟连接线，窗口尺寸改变不重开服务/重置视图。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_replay_view.py tests/test_research_ui.py -q`；预期缺少回放服务/渲染接口失败，不使用公网。
- [ ] **Step 3：实现原生图表适配。** 参考tests/window_smoke.py的已验证离线klines协议，但生产实现不得import测试。服务只提供SDK原生静态资源和已存数据；大量数据按已有柱范围分页，以实际time/id映射，不能截断后宣称完整覆盖。native-replay.js复用chart/board/坐标和SVG覆盖层，点击命中真实成交，展示均线决策值与风险事件。保护路径在状态不可信/停机后断开；价格轴与数据时间保持现有约定。
  结果页基准与成本压力分别标记，比较两个run的参数差异、收益、费用、回撤和期末暴露。关闭实验再打开读取同一SQLite数据；无记录明确提示，不连账户、不静默修复坏结果。关闭回放服务不关闭行情/研究会话。
- [ ] **Step 4：绿测。** 同上并加入tests/test_native_history.py、tests/test_native_tools.py、tests/test_research_results.py；预期全部通过。
- [ ] **Step 5：提交。** 仅git add本任务Files中实际修改文件；`git commit -m "feat: 添加本机成交复盘与实验结果比较"`。

### Task 7：完整操作验收、故障演练和中文使用说明

**Files:** 新建tests/research_workbench_smoke.py、tests/test_research_workbench.py、docs/research-paper-guide.md；修改docs/requirements.md、CLAUDE.md；必要缺陷修复仅限前六任务范围。

**Interfaces:** 接入任务5/6公开接口；测试脚本使用临时实验/结果目录及合成SDK替身，不读取真实凭证，不启真实账户会话。成功输出RESEARCH_WORKBENCH_OK，窗口最终可正常关闭。

- [ ] **Step 1：写端到端失败测试。** 在真实WebView串行走“选择双均线→实际合约→5/20、周期、日期、风险→回测→成交原因→复制10/30→比较→关闭重开复盘”；另走观察/显式模拟、部分成交保护/拒单冻结/断线/取消及窗口退出。以`assert result.returncode == 0`、`assert 'RESEARCH_WORKBENCH_OK' in result.stdout`为外层验收，窗口内探针断言无重复run、实际保护线及R正确、持仓未确认时无平仓成功提示、没有凭证进入公开快照。覆盖960×680窗口不遮挡和已有行情/分屏不反复加载。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_workbench.py -q`；预期若集成缺失则具体断言失败；任务均接齐时此步可先验证测试确实检测断开桥接的故障，再恢复实现，不制造无意义失败。
- [ ] **Step 3：修复集成缺口并写教程。** 教程包含实际中文按钮、首次必填风险字段及换算例、示例周期日期的覆盖限制、1R/2R/3R规则、成交定位、参数A/B与双费区别、模拟显式委托、停止和平仓并停止、断线与1跳费用限制。更新requirements将本轮范围与仍未联网验收分开，地图仅增加入口和短文档链接。
- [ ] **Step 4：最终验证和独立审查。** 运行`.\tools\check.ps1`并核实完整退出码/测试数量；运行`git diff --check`。按用户选择的执行方式进行最终新鲜上下文审查，不把审查转成额外并行功能开发；有发现先复现再修复并重跑受影响检查。缺真实凭证/权限时明确记录尚未联网，不伪称历史策略或模拟委托已验证。
- [ ] **Step 5：提交并交付。** 仅提交本轮变更，推送origin/codex/research-paper-loop；不合并main、不创建PR。交付教程、实际离线证据和本机联网验收操作；如需用户输入凭证，只让其在本机软件输入，不在聊天索取。不自动启动模拟委托。

## 计划自审与执行交接

规格覆盖：设计1—3对应任务1/5；4对应任务2/4；5—6对应任务2；7对应任务3/4/5；8对应任务4；9对应任务3/6；10按文件结构分工；11对应各任务与任务7；12保持不实施。Review Focus五项均已分配具名验收。
用户已确认书面设计与本计划，选择当前会话顺序实施，最终进行一次独立审查；不自动启用模拟委托。
推荐原生执行：由当前会话按顺序完成七个任务，最后一次独立审查；任务间接口紧密，保持一个实施上下文可减少反复交接。
也可选择子代理驱动：每任务由新子代理实现并独立审查，再进入下一个任务，最后整体验证；上下文和审查成本较高。
