# 历史主力连续回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户选择品种、周期及多年日期，在一个SDK回测账户内按历史主力连续交易，移仓保持原逻辑交易的R与保护，支持观看、保存复盘和实验比较。

**Architecture:** 保留固定月份版本1/2，新增版本3连续配置与独立的连续回测执行分支。用天勤公开行情接口取得回放当时的主力，信号序列采用因果向前价差调整；移仓协调器串行平旧开新，逻辑交易以金额延续风险。SQLite区分实际合约、信号序列与逻辑交易，展示层读取白名单快照与有界分页。

**Tech Stack:** Python 3.13.11、TqSdk 3.10.2、Decimal、SQLite、现有JavaScript/WebView2与天勤图表组件；不新增产品依赖。

**Spec:** `docs/superpowers/specs/2026-10-19-historical-main-backtest-design.md`，用户已确认。

## Global Constraints

- 连续实验采用`schema_version=3`、`strategy_version=3`；旧版本1/2原样读取，不自动改写。
- 完整区间使用一个TqBacktest和一个TqSim账户，不为每个月份另启一轮并重置资金。
- 持仓遇到主力换月时，先平旧合约，再接到新主力，延续原方向和风险保护。
- 换月不重置初始R、已达保护档位或初始资金，不把月间价差当作收益。
- 信号使用`X=P-A`，切换时`A_new=A_old+(P_new_ref-P_old_ref)`；共同参考柱在切换时必须已经完成。
- 止损价`stop_new=E+s×(F-C)/(q×m)`；按保护更严格方向取整；费用与毛金额阶梯分列。
- 默认左右各2根完成柱确认严格拐点；默认1R保护至最初交易1跳金额、2R锁0.5R、3R退出。
- 过程图只显示最近500根已处理K线、窗口内最多5000条事件；完整证据保存在SQLite。
- SDK可提前回放预热，用户交易日期不变，预热期间不委托；数据不足明确失败。
- 本轮只做历史回测；现有固定合约模拟保持原行为，不自动启用模拟换月或实盘。
- 使用`.venv-tqsdk`及现有安装/检查入口；凭证、认证对象和原始响应不入记录；不读取封存内容。

## Review Focus

1. TOML省略None字段：版本3的`symbol=None`保存/读取仍一致，旧配置不能因兼容而接受缺失字段；任务1测试。
2. 累计价差导致信号价格为零或负数：数学计算和绘图仍有效，真实行情依然严格要求正数；任务3、6测试。
3. 夜盘、换月双方相同时间戳及日线完成时点：按交易日和序列身份区分，不串柱或提前确认；任务3、4、7测试。
4. 撤单确认与停止/3R/再次换月同一更新到达：按风险优先串行执行，不因旧意图重新开仓；任务5、7测试。
5. 多年分钟数据：运行图与复盘不得全量装入浏览器，按窗口分页，空闲不重复读取整库；任务6、9测试。

## 文件与边界

| 单元 | 新增文件 | 现有接点 |
| --- | --- | --- |
| 连续配置 | `qf/continuous_config.py` | `research_config.py`、`experiment_store.py` |
| 金额风险 | `qf/continuous_risk.py` | 复用`trade_risk.py`规格、`pivot_stop.py`入场计划，不改旧RiskState格式 |
| 因果信号序列 | `qf/continuous_series.py` | `ma_cross.py`、`pivot_stop.py`纯信号，仅显式允许调整价格 |
| 连续证据 | `qf/continuous_journal.py` | `research_journal.py`完整性分派，复用基础Journal订单/成交表 |
| 移仓协调与范围保护 | `qf/continuous_roll.py` | 复用TargetPosTask，旧`safety.py`Guard保持单合约语义 |
| SDK适配与回测循环 | `qf/continuous_runtime.py`、`qf/research_contract.py` | `research_runtime.py`分派、`research_session.py`白名单 |
| 结果与图形数据 | `qf/continuous_results.py` | `research_results.py`、`research_snapshot.py`、`replay_view.py` |
| 连续复盘分页 | `qf/web/continuous-replay.js` | `native-replay.js`、`native-live-research.js`、`research_chart_assets.py` |
| 页面入口 | 无新窗口 | `workbench.py`、`web/research-form.js`、`web/research.js`、`web/research-results.js` |

除表中标明的版本分派与必要公共函数抽取，不重构旧执行框架。下面任务严格顺序执行，功能入口在任务8才开放。
每项先运行失败测试，再做最小实现，回归通过后提交；测试不使用真实凭证、真实账户或用户results目录。
推荐在当前会话由主代理直接执行，因任务共享配置、账本和执行状态接口；最终做一次独立整体审查。
隔离工作区在执行开始时按using-git-worktrees技能处理，不在规划时另建工作区。

---

### Task 1: 版本3配置及实验修订兼容

**Files:** 新增`qf/continuous_config.py`、`tests/test_continuous_config.py`；修改`qf/research_config.py`、`qf/experiment_store.py`。

**Interfaces:** `ContinuousConfig`保留ResearchConfig的共同字段，`symbol: None`，`risk: PivotRiskConfig`；新增`contract_mode='historical_main'`、`signal_adjustment='causal_forward_gap_v1'`、`roll_policy='close_then_reopen_preserve_r_v1'`。`validate_research_config(raw)`返回旧ResearchConfig或ContinuousConfig；`migrate_to_continuous(config, *, name) -> ContinuousConfig`显式复制升级。`ExperimentStore.copy(experiment_id, revision, *, name, upgrade_to_pivot=False, upgrade_to_continuous=False)`增加命名参数，两种升级互斥。

- [ ] 写`test_v3_without_month_roundtrips_toml`：版本3无symbol或None归一为None，保存后读取`.public()`一致；其它缺字段/未知字段拒绝。`test_legacy_configs_are_unchanged`核对v1/2公开字段和磁盘原字节不变。`test_upgrade_creates_new_identity`核对复制的parent、风险上限和新实验id。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_config.py -q`，确认因版本/接口缺失失败。
- [ ] 实现上述类型和分派；抽取共同的日期、均线和PivotRiskConfig校验，禁止用虚构合约代替连续模式做验证。仅v3允许省略symbol，旧版本保持严格字段集；TOML不能写伪造的字符串`'None'`。
- [ ] 重跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_config.py tests/test_research_config.py tests/test_pivot_config.py tests/test_experiment_store.py -q`，均通过。往返关键断言：`assert loaded.symbol is None`、`assert loaded.public() == original.public()`、`assert old_path.read_bytes() == before_bytes`。
- [ ] 提交`feat: 增加历史主力连续实验配置并保留旧修订`。

### Task 2: 逻辑交易的金额风控

**Files:** 新增`qf/continuous_risk.py`、`tests/test_continuous_risk.py`。

**Interfaces:** `LogicalRisk`不可变状态包含trade_id、side、quantity、entry_price、initial_r、sealed、stage、floor_gross、peak_gross、realized_gross、first_offset_amount、exit_reason、last_fill_ns、last_quote_ns，空仓默认值为零/空身份/未封存。提供`apply_logical_fill(state, fill, *, role, spec, entry_plan, risk) -> LogicalRisk`、`seal_logical(state) -> LogicalRisk`、`logical_gross(state, *, price, spec) -> Decimal`、`logical_stop(state, *, spec) -> Decimal | None`、`protect_logical(state, *, price, time_ns, risk, spec) -> LogicalRisk`。entry_plan在初次入场时必须提供，其余role允许None；role限定strategy_open/strategy_close/roll_out/roll_in。

- [ ] 写`test_roll_preserves_r_and_floor_long_and_short`：R=1000、stage=2、F=500、C=1800、q=1、m=10，多头新入场4000时保护3870，空头保护4130；止损处逻辑毛收益均为500。用跳价3验证取整：多头E=4001时保护3873，空头E=4000时保护4128，金额保护不放宽。
- [ ] 写部分成交用例：C累计每笔实际平仓毛盈亏，余仓浮盈不重复算；roll_in不重置R/峰值/档位。首次strategy_open在封存前按实际均价及冻结拐点计算R，封存后不变；3R和固定金额终点均按累计毛收益退出。
- [ ] 写旧仓平完的阈值用例：quantity=0但逻辑交易仍在移仓时，C达到3000则`assert state.exit_reason == 'take_profit'`；C因实际退出滑点跌到F或以下时也结束逻辑交易，不把新合约开仓当作追回已破保护的机会。
- [ ] 运行新测试，确认接口不存在时失败；实现上述Decimal函数，复用既有规格/入场校验。首档金额按最初手数、跳价与配置偏移封存；已有F只能收紧。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_risk.py tests/test_trade_risk.py -q`，均通过。上述多头状态的关键断言：`assert logical_stop(state, spec=spec) == Decimal('3870')`、`assert logical_gross(state, price=Decimal('3870'), spec=spec) == Decimal('500')`；早于last_fill_ns的报价不能改变保护。
- [ ] 提交`feat: 保持跨合约逻辑交易的R与金额保护`。

### Task 3: 因果信号序列与换月依据

**Files:** 新增`qf/continuous_series.py`、`tests/test_continuous_series.py`；修改`qf/ma_cross.py`、`qf/pivot_stop.py`与对应测试。

**Interfaces:** `SignalSeries(period_seconds, *, max_window)`；`switch(*, old_symbol, new_symbol, detected_ns, old_rows, new_rows) -> dict`返回共同完成柱及新旧偏移证据；`append(*, symbol, row, completed_at_ns) -> dict | None`返回一根新增信号柱或去重None；`window() -> list[dict]`仅返回有界已完成序列。首合约通过old_symbol=None、old_rows=[]、new_rows=[]调用switch，偏移为0，首次设置无需双方参考柱；后续切换必须核对共同完成柱。

补充`completed_cross_closed(rows, fast, slow, *, completed_ns, allow_nonpositive=False) -> CrossSignal | None`接受已完成柱，不要求伪造一根形成中柱；旧completed_cross保留语义并复用共同计算。`latest_confirmed_pivot(rows, *, side, left, right, as_of_ns, previous=None, allow_nonpositive=False)`仅在连续信号调用时显式开启。

- [ ] 写`test_gap_only_roll_has_no_cross`：旧参考100、新参考200，新偏移100，新柱201对应信号101；旧柱不重写，切换本身不生成一根信号。对200根恒定走势及不同月份大价差，均线不出现换月假交叉。
- [ ] 写`test_future_and_misaligned_reference_are_rejected`：完成时间晚于detected_ns、不同时间戳或缺共同柱均失败；夜盘按传入SDK完成时间，不用本机日期。重复柱返回None；未完成旧柱不得拼成新柱。
- [ ] 写`test_adjusted_nonpositive_price_is_valid_but_raw_is_not`：A=200、实际OHLC为正且close=190时，`assert adjusted['close'] == Decimal('-10')`；对应负数序列能够生成完成柱交叉及严格拐点，默认旧调用仍拒绝非正真实价格。实际价格0/NaN及坏OHLC失败。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_series.py -q`确认失败，再实现`X=P-A`及共同完成柱选择；输出含source_symbol、offset、原始/调整OHLC、datetime、end_ns、completed_at_ns、completed和交易日，内部纳秒为整数，展示边界转换为字符串。边界舍弃事件返回证据，不以假柱补齐。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_series.py tests/test_ma_cross.py tests/test_pivot_stop.py -q`，确认未来数据变动不影响此前输出，提交`feat: 构建无未来数据的主力连续信号序列`。

### Task 4: 连续回测事务记录与完整性

**Files:** 新增`qf/continuous_journal.py`、`tests/test_continuous_journal.py`；修改`qf/research_journal.py`中的manifest分派。

**Interfaces:** `ContinuousJournal.create(root, mode, config, metadata=None)`及`commit_continuous(event_id, *, time_ns, kind, payload, logical_risk, roll_state, fills, target=None) -> bool`；`capture_signal(row)`、`capture_actual(symbol, period, rows)`、`record_spec(symbol, spec)`、`expected_positions() -> dict[str, int]`。复用基础订单/fills/equity表，`research_schema=2`与旧schema=1区别。

roll_state在账本边界是白名单dict，字段phase、old_symbol、new_symbol、side、requested_lots、started_ns、reason；phase限定old_cancel/old_exit/new_enter/idle/aborting/frozen，不导入下一任务的协调器类。任务5将其RollState用asdict写入。

- [ ] 写`test_fill_risk_roll_state_commit_is_atomic_and_idempotent`：中途异常整体回滚，`assert journal.expected_positions() == {}`；同一fill重放不重复C或数量，`assert replayed is False`；同一时间旧/新合约原始柱可共存，信号柱按唯一序号/时间去重。
- [ ] 写`test_manifest_covers_continuous_evidence`：篡改映射、偏移、逻辑成交关联、逐合约规格任一项均拒绝读取；旧schema=1的manifest算法不改变。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_journal.py -q`确认失败，再建立带索引的`signal_bars`、`main_changes`、`roll_events`、`contract_specs`、`logical_fills`及严格白名单事件。signal_bars独立于真实价格正数检查；kind与payload使用明确枚举/字段，不保存SDK对象。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_journal.py tests/test_research_journal.py tests/test_research_results.py -q`；checkpoint计数在事务内更新，后续快照不反复count整库；CSV含新证据表，提交`feat: 事务保存主力切换与逻辑交易证据`。

### Task 5: 串行移仓协调与执行范围

**Files:** 新增`qf/continuous_roll.py`、`tests/test_continuous_roll.py`。

**Interfaces:** `RollState`含phase(old_cancel/old_exit/new_enter/idle/aborting/frozen)、old_symbol、new_symbol、side、requested_lots、started_ns、reason。`RollCoordinator(state)`提供`request(old_symbol, new_symbol, *, side, lots, now_ns)`、`advance(*, positions, pending_orders, task_finished, risk_exit, stop_requested, mapping, now_ns) -> list[dict]`；动作限定cancel/target/complete/freeze，target含symbol、volume和role。`ContinuousGuard(journal, coordinator, *, fill_handler)`实现tracked_api所需start/check/before_order/accept_fill接口。

- [ ] 写`test_no_new_open_until_old_flat_and_cancel_confirmed`，逐更新核对动作列表；旧仓部分平仍不得开新仓：`assert not any(a['kind'] == 'target' and a['volume'] != 0 and a['symbol'] == new_symbol for a in actions)`。全平/旧挂单结束后仅开原方向原数量，空仓切换无成交；动作字典统一kind字段。
- [ ] 参数测试同一更新到达停止/3R/反向退出/映射再变时，旧新意图不会复活；重放advance不重复目标；旧任务取消未确认不能当作平仓。
- [ ] 写`test_partial_new_entry_is_protected_then_aborted_on_timeout`：部分新仓立即受任务2保护，失败时先取消余单，核实后退出已成交数量；不静默减量继续。新规格乘数变更、最小手数或资金不足产生明确失败。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_roll.py -q`确认失败，再实现协调器。Guard按允许的旧/新合约逐项核对实际仓位与账本，禁止双向/第三方持仓及并发放大暴露；原safety.Guard不扩权。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_roll.py tests/test_runtime_safety.py tests/test_trade_risk.py -q`，提交`feat: 串行执行历史主力移仓并约束未决状态`。

### Task 6: 连续结果、快照和有界复盘

**Files:** 新增`qf/continuous_results.py`、`qf/web/continuous-replay.js`、`tests/test_continuous_results.py`、`tests/continuous_replay_node.js`；修改`qf/research_results.py`、`qf/research_snapshot.py`、`qf/replay_view.py`、`qf/research_chart_assets.py`、`qf/web/native-replay.js`、`qf/web/native-live-research.js`、`tests/test_research_ui.py`。

**Interfaces:** `read_continuous_run(root, run_id, *, details=False) -> dict`、`summarize_continuous_run(root, run_id) -> dict`、`continuous_snapshot(journal, config, quote, *, now, revision, progress, terminal=False) -> dict`。复盘`series=signal|actual&symbol=...`为显式白名单；`bars(offset, limit)`最多10000根，附稳定global_id；`locate(time_ns, *, series, symbol=None)`返回索引与加载窗口。旧schema分支接口保持。

- [ ] 写收益对账测试：C=1800的roll_out不算结束一笔逻辑交易；最终策略退出`assert summary['closed_trade_count'] == 1`，全部roll费用入净收益且单列，`assert Decimal(summary['net_pnl']) == sdk_end_balance - initial_equity`。篡改symbol/偏移/成交关联会拒绝，不以宽松“任意合约”绕过校验。
- [ ] 写同时间双方柱的序列筛选测试；连续图只读取signal_bars，实际图必须指定保存过的symbol。箭头字段display_price=actual_price-offset，详情保留price；风险线同样转换，原始金额不变。
- [ ] 写合成1200000根分页测试：运行快照最多500柱/5000事件；初次复盘只取末尾2000柱，浏览到边缘或按年份/成交定位再加载目标窗口。客户端最多保留10000柱，空闲不轮询整库/全量K线；新JS测试脚本注册现有Node测试入口。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_results.py tests/test_research_ui.py -q`确认失败，再实现只读schema分派和indexed分页。图表的global_id稳定，异步响应校验run_id/series/request_id，过期响应不覆盖新选择；负信号价格可绘制，真实成交价格仍必须为正。
- [ ] 展示主力换月标记及真实成交价格；比较要求模式、拼接、移仓政策与区间一致，SDK分段统计与逻辑统计分列。运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_results.py tests/test_research_results.py tests/test_replay_view.py tests/test_research_live_view.py tests/test_research_ui.py -q`通过，提交`feat: 展示连续交易证据与分页复盘`。

### Task 7: 单会话SDK回放与预热/覆盖核对

**Files:** 新增`qf/continuous_runtime.py`、`qf/research_contract.py`、`tests/continuous_sdk.py`、`tests/test_continuous_runtime.py`；修改`qf/research_runtime.py`、`qf/research_session.py`。

**Interfaces:** `execute_continuous(config, root, credentials, *, sdk, fee_multiplier=1, stop_requested, progress, view_progress, experiment_ref) -> dict`与现有execute_research返回同样的status/reason/run_id/summary；仅backtest分派至此。公共`contract_spec(api, account, symbol, quote, *, paper, multiplier)`移至research_contract，旧runtime保留导入别名。测试`ContinuousSdkFixture(events, *, faults=None)`提供SDK兼容替身及calls记录。消费任务6的continuous_snapshot及summarize_continuous_run，不在循环里再写一套报表计算。

- [ ] 写合成SDK用例覆盖两个年度、三次主力切换：`assert fixture.calls['TqApi'] == fixture.calls['TqBacktest'] == fixture.calls['TqSim'] == 1`、`assert result['summary']['roll_count'] == 3`；初始资金只设置1次、旧新实际成交顺序正确；每次切换配置的signal_adjustment/roll_policy始终一致。
- [ ] 写`test_prewarm_uses_historical_mapping_without_orders`：SDK可提前回放，预热柱经过任务3；不足慢均线/拐点窗口失败，用户起始日前没有委托。用SDK交易日历选更早起点，至少需要`max(slow_period+2, pivot_left+pivot_right+2)`根有效完成柱，元数据保存引擎/用户起点。
- [ ] 写夜盘、日线最终CLOSE、最后一根未完成柱、缺日历/映射/行情/参考柱、Tick无权限、历史停滞、终点仍移仓未决等测试；错误均有白名单context(date/symbol/data_type)，不切换精度或日期。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_runtime.py -q`确认失败，再实现一条SDK事件循环，使用公开get_quote/get_kline_serial/get_tick_serial/wait_update及交易日历；按已收到映射选择实际symbol，调用任务2—6。负信号拐点先加当前偏移转回真实价格，再调用plan_pivot_entry；转换后的止损非正则跳过入场，不放宽真实价格校验。TargetPosTask统一管理目标，不混用手工下单；完成/异常均finally释放API。
- [ ] SDK warmup阶段单列进度；交易区间复用BacktestProgress，换月不重置，保存与覆盖核对之前不100%。Session新增严格白名单logical_risk、roll、failure_context，派生兼容的risk显示值，不传原始异常。
- [ ] 核对每个交易日实际主力的数据和已记录边界舍弃；期末保留实际未实现盈亏，未决移仓标不完整。运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_runtime.py tests/test_pivot_runtime.py tests/test_research_session.py tests/test_sdk_loop.py -q`通过，提交`feat: 接入单账户多年主力连续回测`。

### Task 8: 工作台连续模式入口

**Files:** 修改`qf/workbench.py`、`qf/web/research-form.js`、`qf/web/research.js`、`qf/web/research-results.js`；新增`tests/test_continuous_bridge.py`、`tests/continuous_form_node.js`，修改`tests/test_research_ui.py`。

**Interfaces:** `WorkbenchBridge.start_research(experiment_id, revision, mode, activate=False, resume=None, fee_multiplier=1)`参数不变；根据配置分派，v3不要求固定月份查询快照，仅允许backtest。显式`copy_continuous_experiment(experiment_id, revision, name)`调用任务1的copy(upgrade_to_continuous=True)新建parent副本；前端模式historical_main/fixed，fixed保存原v2字段，continuous保存任务1字段。

- [ ] 写桥接测试：多年v3保存/启动不填symbol、不调用单月份discover，`assert response['ok'] and discover_calls == []`；v2保留到期预检；v3启动paper在创建任务/取凭证前明确拒绝：`assert not response['ok'] and session.thread is None`。旧v2转连续必须创建新id，原修订字节不变。
- [ ] 写Node测试：新实验默认连续，品种/周期/起止日期可选，月份输入和查询按钮仅fixed显示；既有v1/2不自动转换，提供明确复制按钮。模拟页新建固定模板；加载连续实验提示仅历史用途且不能启动。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_bridge.py tests/test_research_ui.py -q`确认失败，再接入上述入口。修改模式不能把当前已保存实验静默改版；给已保存实验切换模式需明确复制，新建模板才直接切换。
- [ ] 状态显示当前实际主力、换月次数、逻辑交易数和具体失败日期/合约；旧失败后的静止进度/空图保护继续有效，费用压力回放直接使用同一v3修订。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_bridge.py tests/test_research_ui.py tests/test_research_terminal_state.py tests/test_pivot_bridge.py tests/test_credentials.py -q`，提交`feat: 默认提供历史主力连续回测入口`。

### Task 9: 完整操作验收、说明与交付

**Files:** 新增`tests/continuous_workbench_smoke.py`、`tests/continuous_workbench_browser.js`、`tests/test_continuous_workbench.py`；修改`docs/requirements.md`、`docs/research-paper-guide.md`、`CLAUDE.md`。

**Interfaces:** 使用任务7的ContinuousSdkFixture、临时实验/results目录、内存凭证和真实WebView2，显式禁止真实TqApi；无新产品接口。

- [ ] 先写失败操作验收：用户选跨年日期无需月份→观看回放跨换月→收起/展开不重启→查看真实移仓成交→复制改均线比较→退出后无凭证重新复盘。验证逻辑交易数与实际成交数不同且有中文说明；Python外层用`assert result.returncode == 0`及`assert 'CONTINUOUS_WORKBENCH_OK' in result.stdout`核对真实窗口流程标记。
- [ ] 加失败路径：无历史映射/账户权限不足有具体日期与合约、终态不动画、不显示空图等待；重试不重复旧job。多年复盘按年跳转/拖动取窗口，不能一次加载全部1200000根。
- [ ] 先运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_workbench.py -q`确认新操作路径缺失时失败；实现所需小范围连接修正后，串行运行该测试及`tests/test_research_workbench.py`，避免窗口并行互相干扰；覆盖既有固定合约、模拟观察/委托/停止和正常退出。
- [ ] 更新说明与需求状态：默认多年连续、信号价格/实际价格的区别、移仓延续R的1000/1800/500例子、费用模型来源、旧记录/模拟边界；不将短样本写为用户日期限制。
- [ ] 运行`.\tools\check.ps1`与`git diff --check`，全部通过后提交`docs: 交付历史主力连续回测及验收说明`；最终检查针对最终代码，之后不无故重复全量测试。
- [ ] 一次新鲜的整体审查：核对未来数据、资金/R连续、未决订单、完整性及大范围复盘。审查问题修复后运行相关测试及项目必需检查；不派发多个重复审查。
- [ ] 提供本机联网验收操作，沿用用户选择的品种、周期、日期；核对映射和历史权限后执行实际包含换月的回测。缺权限明确给证据，不偷偷换区间；未经实际运行不宣称多年账户验收完成。
- [ ] 保存并正常推送`codex/research-paper-loop`至原GitHub仓库（执行如在隔离工作区，完成后按原分支整合流程处理，不强推）；报告最终提交、测试结果及实际联网边界。

## 计划自审与执行交接

- 设计覆盖：配置/页面→任务1、8；因果信号与预热→任务3、7；移仓与金额保护→任务2、5、7；记录/复盘/比较→任务4、6；完整验证与说明→任务9。
- 类型一致：任务1的ContinuousConfig仅进任务7连续执行分支；任务2的LogicalRisk由任务4严格序列化，任务5协调不另建R；任务6按schema选择证据，不套旧单symbol约束。先建立结果/快照接口，再由任务7消费，避免前置任务依赖后置实现。
- 当前任务为计划编写，尚未修改产品功能。任务内命令使用项目解释器；列出的旧测试路径已核对存在，不能用占位测试冒充通过。
- 推荐执行方式：当前会话直接实施，每项按失败测试→实现→回归→提交推进，最后一次独立整体审查。另一选择为逐任务子代理实现与审查，会增加上下文及审查开销。
- 本计划需用户审阅并选择执行方式后启动；设计确认不自动代表计划已审阅。
