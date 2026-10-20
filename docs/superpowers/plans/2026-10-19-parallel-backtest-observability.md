# 多实验并行回测与可信观测 Implementation Plan

> 历史状态：本计划的任务池、独立worker、账户和保护证据已实现并从后续主路线继承。
> 后续性能、完整观察窗、槽位编排和本地快速引擎以
> `2026-10-20-complete-observer-and-slot-workflow.md`和
> `2026-10-20-local-fast-backtest-engine.md`为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户能核对每笔止损和账户变化，在当前回测继续运行时创建另一品种/周期的并行回测，独立切换、停止、复盘及比较。

**Architecture:** 先交付单项回测的账户证据、保护轨迹及性能基准，再用小型任务管理器将现有执行器放进独立Windows spawn子进程。实验修订、资金、SDK与结果各自隔离；父进程只管容量、控制、有限快照和退出，模拟保持现有单账户控制。

**Tech Stack:** Python 3.13.11、TqSdk 3.10.2、multiprocessing spawn、SQLite、现有JavaScript/WebView2和天勤图表；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-19-parallel-backtest-observability-design.md`，用户已审阅确认。

## Global Constraints

- 版本2固定合约及版本3主力连续回测可并行；版本1只读复制升级。配置版本、已有实验修订和旧结果不静默改写。
- 每项一个TqApi、一个TqBacktest、一个TqSim；默认2项并发，可设置1—4项；超过容量明确等待，不能冒充正在计算。
- 快期模拟仍串行、保留账户锁；任务入口只接受backtest，无实盘入口，不合计独立账户为组合收益。
- 凭证仅通过父子私有内存通道传入，不进命令行、日志、任务存根、结果或原始错误；现有安全登录入口保留。
- 运行图最近500根、窗口最多5000条事件；账户每类列表最多500条；未观看任务不构造重型图形快照，单项观看约0.2秒节流。
- 新账户证据标记account_schema_version=1，纳入完整性；旧格式按旧算法只读，缺失字段不补0。
- 累计费用与日内费用分列；正常完成与SDK统计相差超过0.01元不能标记成本核对通过。
- 保留成交、订单用途、风险/目标和移仓确认事务强度；不关闭同步落盘、不略过权限/覆盖/CLOSE证据核对换速度。
- 纳秒时间以字符串过桥；所有任务消息核对job_id、run_id、进程代号与各流递增序号。
- 退出清理总预算为所有活动任务执行超时最大值加5秒，不能按任务数串行倍增；只结束本次会话可验证拥有的子进程，未确认不记成功。
- 使用`.venv-tqsdk`及`tools/setup.ps1`、`tools/check.ps1`；不读取封存内容，不接用户真实账户做离线测试。

## Review Focus

1. 左侧窗口之前已开仓、窗口内没有保护变化，仍能看到初始/当前止损；同柱极短段与0/负信号坐标不能消失。任务3、4覆盖。
2. 观察A→B→A期间有迟到帧、迟到终态和账户快照，不能串账户、串图或改编辑草稿。任务6、8、9覆盖。
3. 工作进程崩溃、父管道断开、退出中图形队列已满或PID已失去归属，停止不能卡死、误杀其他进程或伪造完成。任务6、7、10覆盖。
4. SDK日内费用清零、新模型表被删除、旧文件缺字段及合法0，必须分清费用口径、损坏和未记录。任务2、4覆盖。
5. 完成柱OHLC不变但到达SDK CLOSE、已有完成柱被改写、换月参考历史被去重，性能优化不能漏信号或引入未来数据。任务1、5覆盖。

## 拆分与交付边界

本计划是一条有共享契约的研究流程，分两段可独立验收的交付：任务1—5使单项回测可核对且消除已确认展示开销；任务6—10接入并行及页面；任务11完成整体交付。账户、保护段、观看开关先冻结接口，后面的任务不重新定义它们。执行时逐任务TDD和提交，不在规划阶段创建产品骨架。

| 单元 | 新增文件 | 修改接点 |
| --- | --- | --- |
| 执行正确性回归 | `tests/test_continuous_execution_contract.py` | `continuous_runtime.py`、`research_contract.py`、测试SDK替身 |
| 账户证据 | `qf/research_account.py`、`tests/test_research_account.py` | 两执行器、账本、完整性、结果读器 |
| 保护段 | `qf/research_protection.py`、`tests/test_research_protection.py` | 快照、窗口读器、复盘API |
| 账户/保护图层 | `tests/research_observation_node.js` | `account-view.js`、`native-replay.js`、`research.js`、图形服务 |
| 增量与测量 | `qf/research_serial_cursor.py`、`tests/research_perf_probe.py`、`tests/test_research_performance.py` | 连续热循环、两执行器发布、ResearchSession |
| 子进程协议 | `qf/research_protocol.py`、`qf/research_worker.py`、`tests/research_worker_probe.py`、`tests/test_research_worker.py` | 执行器可选参数、来源元数据 |
| 任务管理 | `qf/research_jobs.py`、`tests/test_research_jobs.py` | 工作台生命周期 |
| 明确任务桥接 | `qf/research_jobs_bridge.py`、`tests/test_research_jobs_bridge.py` | `workbench.py`、`LiveResearchView`、桌面入口 |
| 任务页面 | `qf/web/research-jobs.js`、`tests/research_jobs_node.js` | `research.js`、表单、index/CSS |
| 完整操作 | `tests/parallel_workbench_smoke.py`、`tests/parallel_workbench_browser.js`、`tests/test_parallel_workbench.py` | 现有窗口验收、说明与需求 |

`qf/`和`qf/web/`前缀下未写全的修改接点分别指现有同名Python与JavaScript文件。不得把这些责任全部塞进已经较大的workbench.py或continuous_runtime.py。

---

### Task 1: 执行正确性与可比较基准

**Files:** 新增`tests/test_continuous_execution_contract.py`；修改`qf/continuous_runtime.py`、`qf/research_contract.py`、`qf/research_runtime.py`、`tests/continuous_sdk.py`。

**Interfaces:** 连续`consume()`仍返回最新可执行完成柱的`CrossSignal | None`。新增`make_target_task(sdk, api, symbol, quote)`统一现有`offset_priority='今,昨,开'`与SDK最小开仓支持；不改变定仓规则。连续普通反向交叉保存同合约信号及当时确认拐点，取消/平仓确认后才反手；停止、其他风险退出和换月取消该反手意图。

- [ ] 写`test_confirmed_reverse_survives_exit_confirmation`：持多→一次死叉→下一更新才平仓→无第二次死叉仍按原确认拐点申请空仓；断言`targets`先0后负，未空仓/撤单确认前无负开仓。写停止/换月取消pending反手的对称断言。
- [ ] 写`test_target_supports_sdk_minimum_open_volume`：最小限价5、计划5手时factory显式支持；不足5手仍拒绝。覆盖仅市价最小量>1时SDK的构造检查，不擅改限价定仓步长。替身构造/取消语义与锁定SDK对照，不能用同步假成交掩盖路径。
- [ ] 写`test_batch_prefix_cross_is_recorded_without_late_entry`：fast2/slow3，close=[103,102,101,104,105]，中间交叉不得在末柱补做委托，保存`skipped`及`historical_signal_superseded`。写`test_warmup_prefix_cannot_become_start_day_entry`及恒定OHLC的CLOSE完成证据测试。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_execution_contract.py -q`，记录与上述缺陷一致的RED；若候选未复现，保留验证证据，不臆造修改。固定1手反手用`assert target_volumes == [1, 0, -1]`核对目标顺序，未确认阶段用`assert -1 not in target_volumes`。
- [ ] 实现最小修复，按既有版本2先平后反规则，不自动追做换月期间过时信号；保存原始信号及拐点，不使用后来确认的更近拐点替代。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_continuous_execution_contract.py tests/test_continuous_final_review.py tests/test_continuous_runtime.py tests/test_pivot_runtime.py tests/test_runtime_safety.py -q`，预期全部PASS。
- [ ] 提交`fix: pin continuous execution before performance comparisons`。将有意修复造成的成交变化单列，后续性能比较以此修正基准冻结，不重写旧结果。

### Task 2: 账户与费用的可选证据模型

**Files:** 新增`qf/research_account.py`、`tests/test_research_account.py`；修改`qf/research_journal.py`、`qf/continuous_journal.py`、`qf/research_runtime.py`、`qf/continuous_runtime.py`、`qf/research_results.py`、`qf/continuous_results.py`、`tests/test_research_journal.py`、`tests/test_continuous_journal.py`、`tests/test_research_results.py`、`tests/test_continuous_results.py`。

**Interfaces:**

- `enable_account_evidence(journal) -> None`：仅新backtest调用，原连接内建`research_accounts(seq INTEGER PRIMARY KEY,time_ns INTEGER,trigger TEXT,data TEXT)`和`research_fill_fees(fill_key TEXT PRIMARY KEY,amount TEXT,role TEXT)`，写`account_schema_version=1`，建立时间/序号索引。纸面模拟和旧只读文件不升级。
- 两个`commit_update/commit_continuous`增加可选关键字`fill_fees: list[dict] | None=None`；每项只能含`{fill_key,amount,role}`，role限ROLES且amount为有限非负十进制字符串，启用新模型后须与本次新成交一一对应，跟成交/风险同事务落盘。连续费用与原logical_fills费用核对，不重复收取。
- `account_snapshot(api, *, time_ns:int, totals:dict, status:str) -> dict`只取SDK白名单。totals只能含`commission_total,roll_commission,actual_fill_count,closed_trade_count,open_position`且值类型分别为非负十进制、非负十进制、非负整数、非负整数、整数。公共结构`{kind:'backtest',time_ns:str,status,summary,positions,orders,trades,truncated}`，status限定active/last_snapshot/legacy_partial；summary含`balance,float_profit,margin,available,commission,commission_total,roll_commission,actual_fill_count,closed_trade_count,open_position`。commission是SDK日内值；两项费用按去重成交累加；计数按填充/逻辑交易/当前持仓分别生成；列表各最多500条，非有限/缺失值为None，合法0保留。
- `save_account(journal, snapshot, *, trigger:str) -> None`写完成柱、成交、保护档位/合约段变化和终态采样，触发类型限定`bar_close,fill,protection,roll,terminal`。每个历史采样只存摘要与当时持仓，委托/成交以既有账本为证据，不为每柱复制500条全历史列表；终态在state保存一次完整末次快照。`read_account(db, *, at_ns:int | None) -> dict`读不晚于时点的最后seq；None读末次，旧格式返回`status='legacy_partial'`与可核实字段。增加`availability`按summary/positions/orders/trades标明能否核实；未保存的历史委托状态显示未记录，不当成无委托。
- `account_window(db, *, first_ns:int, as_of_ns:int, limit:int=5000) -> dict`返回`{seed,samples,truncated}`：左侧最后状态种子和窗口内轻量采样（seq、time_ns、summary、positions、availability）；并入运行图的account_history，不携带重复委托/成交大列表。窗口内超限位置明确未载入，不用最新余额替代。父进程不为光标历史读取活动SQLite。

- [ ] 写`test_account_fields_zero_missing_and_no_credentials`，断言`summary['balance']==100000`、`summary['float_profit']==0`、`summary['margin'] is None`，认证额外字段不入快照；写`actual_fill_count=161`、`closed_trade_count=80`、`open_position=10`分别保留，同一纳秒多个节点按seq取末次、光标不读取未来节点和采样不重复复制历史列表的测试。
- [ ] 写跨交易日费用测试：第1日7元，第2日3元，累计10元，不等于末日3元；重复成交key累计不变、移仓费用是总额子集。写事务失败触发器，断言费用、成交、风险均回滚。写SDK差额0.01元允许、0.0101元不能通过成本核对的测试。
- [ ] 写旧schema1/2文件哈希与manifest不变、新模型删除表/标记/费用行被拒绝的测试。旧连续停止记录按logical_fills求累计费用；旧固定记录保留已存total_commission/费用口径，不能把单日字段冒充累计。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_account.py -q`确认因缺新模型而RED。
- [ ] 实现白名单、两表、显式版本分派与CSV/完整性接入。新标记或新表任一存在即执行新模型严格核对；旧算法不因自动建空表改变。新固定成交费用取已冻结spec，连续取对应合约spec；异常缺费用明确失败。
- [ ] 在两个历史执行分支接入，保持原equity表兼容、完整手续费停止时也可用；账户采样与发布不发委托。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_account.py tests/test_research_journal.py tests/test_continuous_journal.py tests/test_research_results.py tests/test_continuous_results.py tests/test_pivot_runtime.py tests/test_continuous_runtime.py -q`，预期全部PASS。
- [ ] 提交`feat: persist source-backed backtest account evidence`。

### Task 3: 有界保护轨迹与原始决策查询

**Files:** 新增`qf/research_protection.py`、`tests/test_research_protection.py`；修改`research_snapshot.py`、`continuous_results.py`、`research_results.py`、`replay_view.py`、`research_journal.py`及`workbench.py`结果详情接点。

**Interfaces:** `protection_window(db, *, first_ns:int, as_of_ns:int, series:str, symbol:str | None=None, limit:int=5000) -> dict`返回`{segments,pivots,truncated}`。segment固定为`{trade_id,source_symbol,kind,start_ns,end_ns,actual_price,display_price,quantity,stage,reason}`，kind为initial/active；时间为纳秒字符串、价格十进制字符串。`trade_explanation(db, *, fill_key:str) -> dict`返回原信号、当时entry_plan/pivot、当前/历史保护节点及退出原因；不重新计算策略。版本1/2与连续risk分别适配。

- [ ] 写`test_protection_carries_left_seed_and_open_tail`：开仓在窗口之前、窗口没有事件，仍有当前段并止于as_of。写同柱多次变化有节点、平仓立即断开、部分成交数量变化可见的测试。
- [ ] 写0/负display_price、多空、多次换月和偏移投影测试：actual价保留，roll_out到roll_in之间无线，原合同initial线不冒充新合同真实初始止损。断言`all(int(s['end_ns'])<=as_of for s in segments)`。
- [ ] 写说明测试：entry3301、lots5、R850、stop3284、预算1000；pivot确认时间不晚于原信号；1R/2R移动有实际前后价；缺失的旧决策字段显示未记录。窗口/页数/单笔查询有明确上限，不全载整库。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_protection.py -q`确认RED。
- [ ] 实现左侧有效状态种子、末段裁剪、同值绘制合并及交易/合约分段；原事件不删。新增索引只在新写入账本建，旧读器不为加索引修改文件。
- [ ] 将`protection`与任务2的`account`加入快照/复盘页，运行帧另含account_history；复盘增加只读`/account?time_ns=...`返回`{run_id,revision,requested_time_ns,account}`，由已验证结果读器处理；新桥接`get_research_trade(run_id,fill_key)`返回白名单说明。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_protection.py tests/test_research_account.py tests/test_research_results.py tests/test_continuous_results.py tests/test_replay_view.py tests/test_research_live_view.py -q`，预期全部PASS。
- [ ] 提交`feat: expose bounded stop traces and trade explanations`。

### Task 4: 账户、止损和成交原因真正进入界面

**Files:** 修改`qf/web/account-view.js`、`native-replay.js`、`native-live-research.js`、`continuous-replay.js`、`research-results.js`、`research.js`、`qf/research_chart_assets.py`及必要CSS；新增`tests/research_observation_node.js`，修改`test_research_ui.py`及现有真实窗口验收。

**Interfaces:** `QfAccountView.create(root, {scenario:'research'|'market',onCollapse})`保留原默认market；update接受任务2结构，market原结构不变。`QfNativeReplay.attach(chart,{onFill,onTime})`消费任务3的protection；onTime给出不晚于图中as_of的所选柱完成时间。运行iframe从account_history选不晚于光标的采样；离线iframe用/account查询。两者向所属父页面发送`{kind:'qf-research-account',run_id,time_ns,account,generation或revision}`，分别沿用运行/复盘绑定校验。账户区位于父页面图下，复用该页面已有中文品种标签；不从父进程查询活动SQLite。

- [ ] 写Node失败断言：有效0显示0、缺失显示未记录；三种费项单位元且不混用；market原标题保留；research标题为本次回测账户。161条成交和80笔完整交易分列。
- [ ] 写保护绘制测试：默认initial/active开启、开关不调用执行API，0/负投影可绘制；极短段可点击；点击成交能看到3284止损及确认拐点。写迟到/account响应不得覆盖较新光标时刻或其他run的断言。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_ui.py -q`，新脚本缺实现应RED。
- [ ] 在research.js及research-results.js各自图下挂单一账户区，核对iframe来源/绑定/光标请求序号后更新；对应观察区未显示时隐藏。研究图内原空原生账户区仅在替代面板就绪后隐藏，保留账户折叠和图形大小；现有行情账户不动。SVG只消费段契约，禁止Number(price)真值过滤有效0。
- [ ] 在真实WebView2合成验收中加入账户五字段、停止末次状态、保护线节点点击及光标历史账户；明确来源、实际价/信号价、风险预算与实际R。iframe打开/关闭不启动SDK。
- [ ] 串行运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_ui.py tests/test_market_account.py tests/test_research_workbench.py tests/test_continuous_workbench.py -q`，预期全部PASS。
- [ ] 提交`feat: show backtest funds and inspectable stop protection`；此时单任务观测可独立交付。

### Task 5: 增量处理与真正的快跑开关

**Files:** 新增`qf/research_serial_cursor.py`、`tests/test_research_performance.py`、`tests/research_perf_probe.py`；修改`qf/research_runtime.py`、`qf/continuous_runtime.py`、`qf/continuous_series.py`、`qf/research_session.py`、`tests/test_continuous_execution_contract.py`、`tests/test_continuous_final_review.py`、`tests/test_continuous_runtime.py`、`tests/test_pivot_runtime.py`、`tests/test_research_progress.py`、`tests/test_research_session.py`。

**Interfaces:** 新增`SerialCursor.read(serial, *, period:int, now:int, backtest, symbol:str) -> list[dict]`仅返回新增完成柱。`ContinuousLoop.closed_rows(symbol, now, *, for_reference=False)`正常用游标，换月参考明确走现有completed_rows全部有界参考路径。新增`ViewDemand`（锁保护的enabled、generation；`set(enabled,generation)`、`wants_frame()->bool`），`execute_research(...,view_requested=None,job_binding=None)`向固定/连续分支传递；None保持现有兼容，新的任务路径显式传predicate。进度/账户轻量发布约0.5秒，事件与终态可立即发布，持久化不依赖节流。

- [ ] 写`test_duplicate_updates_do_not_reappend_history`：1000次不变更新旧柱append次数不随200柱窗口倍增，新增完成柱恰好处理一次。写OHLC恒定但CLOSE仍新增、旧完成柱变更Frozen、nan形成柱不提前使用、旧新共同参考仍可取得的测试。
- [ ] 写`test_fast_watch_and_switch_have_identical_outcomes`：同一冻结输入比较signal/target/fill/fees/equity/status；快跑图形构造计数0，观看计数>0，关观看立即停止重型构造；显式复盘不启动API。旧CLI默认调用继续兼容。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_performance.py -q`确认RED。
- [ ] 实现有界窗口指纹游标，先用矢量化比较确认新增/改写，再转换相应行；完成时点独立于OHLC改变，使用既有SDK完成证据，不缓存未来完成状态。不丢掉完成柱改写检查。
- [ ] 接观看predicate，后台仍保存任务2账户采样及任务3风险证据，关闭iframe不影响计算。将计时探针写为只使用合成SDK的测试工具，按SDK等待/生产数据处理/策略/存储/快照分项记录；3次中位数与结果摘要指纹输出JSON，替身耗时单列。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_performance.py tests/test_continuous_execution_contract.py tests/test_continuous_final_review.py tests/test_continuous_runtime.py tests/test_pivot_runtime.py tests/test_research_progress.py tests/test_research_session.py -q`，预期全部PASS。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B tests/research_perf_probe.py --repeat 3 --updates 1000`。报告固定为`mode,elapsed_seconds,stage_seconds,frame_builds,append_calls,trade_fingerprint`及3次中位数；断言`fast['frame_builds']==0`、`fast['trade_fingerprint']==watch['trade_fingerprint']`，记录原/新差异，不承诺未经联网验证的倍数。
- [ ] 提交`perf: skip repeated history and unsubscribed chart work`。

### Task 6: 独立工作进程与有限协议

**Files:** 新增`qf/research_protocol.py`、`qf/research_worker.py`、`tests/research_worker_probe.py`、`tests/test_research_worker.py`；修改两执行器的job_binding来源元数据及白名单。

**Interfaces:**

- `FrozenBacktest`不可变字段：job_id、epoch（各32位小写hex）、config_json、experiment_ref_json、fee_multiplier、source_json；无凭证。`freeze_backtest(config,experiment_ref,*,job_id,epoch,fee_multiplier,source)->FrozenBacktest`只准v2/v3和backtest，内部存规范JSON字符串以便spawn和深度冻结；config/experiment_ref/source属性每次返回解码副本。
- 消息`{job_id,epoch,run_id,stream,seq,kind,payload}`：stream为status/frame/terminal，各自seq严格递增，避免不同通道先后到达误杀所有图帧。kind为ready/state/frame/result/error；run_id启动前可None，确定后不可换。校验函数`accept_message(task, message, *, last_seq:dict, bound_run_id:str | None) -> dict | None`；管理器绑定首次非空run_id，之后不得更换，payload只接受任务2/3/5的字段及既有安全状态结构，未知字段拒绝。
- `worker_main(task, credential_pipe, control_pipe, status_queue, frame_queue, terminal_pipe, stop_event, *, execute_fn=None)`是可导入顶层入口，execute_fn仅测试依赖注入，不由页面或任务文件指定。credential_pipe与terminal_pipe为单向Pipe；status/frame队列各maxsize=1、覆盖旧展示消息；单帧上限8MiB。stop_event独立于图形/命令队列；terminal/ready用可靠小消息，结果只发身份和终态，详情读已关闭结果。
- 控制只允许`set_watch(enabled,view_generation)`；观看代号随切换递增，帧须回传。任务5的job_binding参数以`{job_id,epoch}`写入新运行state/元数据并纳入完整性；旧调用None不变。公开任务status统一为waiting/starting/warmup/backtesting/stopping/saving/backtest_finished/stopped/failed/frozen/interrupted，worker将旧执行器进度映射到这些状态，paper不使用此协议。

- [ ] 写真实spawn测试`test_two_workers_overlap_with_distinct_pids`：使用可导入离线执行探针和共享测试屏障，断言两PID不同、运行区间重叠、各自run_id/资金独立，禁止真实TqApi。不得只mock两个Thread或顺序完成。
- [ ] 写身份/各流乱序/观看代号/超大帧拒绝测试；在一条满图形队列下stop_event仍能触发清理；父控制管道EOF触发停止。验证None兼容和task绑定不能由另一run冒充。
- [ ] 写凭证哨兵测试：仅私有credential_pipe一次传输，所有公开消息、结果、存根、日志均无哨兵；子进程异常只回安全原因，不回repr/traceback认证对象。测试代码不打印哨兵。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_worker.py -q`确认RED。
- [ ] 实现spawn入口、每进程日志隔离、控制检查与ViewDemand；入场、信号、账户采样仍复用execute_research。关闭无用管道端，展示队列不能在进程退出时等待不可完成的flush。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_worker.py tests/test_research_session.py tests/test_credentials.py tests/test_continuous_runtime.py tests/test_pivot_runtime.py -q`，预期全部PASS。
- [ ] 提交`feat: isolate backtests in bounded spawned workers`。

### Task 7: 任务管理、容量与异常恢复

**Files:** 新增`qf/research_jobs.py`、`tests/test_research_jobs.py`；消费任务6探针。

**Interfaces:** `ResearchJobs(results_root, jobs_root, *, capacity=2, worker_target=None)`持项目管理器内核锁；worker_target只测试注入。`submit(config, *, credentials, experiment_ref, include_fee_stress=False, request_id:str)->dict`返回`job_ids,selected_job_id`；相同request_id和参数幂等，不同参数重用拒绝。`list()->list[dict]`、`snapshot(job_id)->dict`、`live_snapshot(job_id)->dict|None`、`stop(job_id)->None`、`set_watch(job_id|None,enabled)->None`、`set_capacity(value)->None`、`close()->bool`。

公开state含job_id、epoch、run_id、status、running（bool）、config、experiment_ref、fee_multiplier、parent_job_id、progress、account、risk、pid/启动时刻及安全reason；不含凭证或进程句柄。等待状态有reason=capacity或baseline_pending。双费提交时冻结成两项，压力任务等基准成功后启动；基准停止/失败则取消尚未启动的压力任务，结果不互相覆盖。

- [ ] 写容量2实际运行2项、第三项等待、降低1不杀既有项、值0/5/True拒绝、同请求幂等及不同请求可重复实验的测试。等待任务配置在编辑区改动后保持冻结。
- [ ] 写A继续而B独立停止/崩溃，结果/账户不串，等待取消不启动进程，双费身份及取消依赖测试。父进程不读活动SQLite；仅收到终态或进程退出后验证结果路径/manifest/job_binding。
- [ ] 写管理器锁测试、重开不重跑、存根断电写入仍保持原子文件测试；活动进程失联不能标100%。恢复只读已有结果，缺可靠归属不按旧PID杀进程。持久化存根没有credential、原始异常及任意路径。
- [ ] 写退出所有任务在`max(execution_timeout_seconds)+5`一次总预算内、队列满/子进程无响应仍能返回、排队任务取消和超时标interrupted的测试。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_jobs.py -q`确认RED。
- [ ] 实现容量槽/FIFO等待、独立监视与公开消息校验、临时文件原子替换存根；stop/set_watch/list不在持锁状态做长join。只持有本次创建的Process对象/句柄才允许清理。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_jobs.py tests/test_research_worker.py tests/test_market_shutdown.py -q`，预期全部PASS。
- [ ] 提交`feat: supervise parallel research jobs independently`。

### Task 8: 工作台桥接与安全兼容

**Files:** 新增`qf/research_jobs_bridge.py`、`tests/test_research_jobs_bridge.py`；修改`qf/workbench.py`、`qf/research_live_view.py`、`tools/workbench_entry.py`。`ResearchJobsBridge`承载仅回测任务的桥接方法和任务池生命周期，`WorkbenchBridge`只委托并保留行情、模拟和既有方法。

**Interfaces:** 新桥接`start_backtest(experiment_id,revision,include_fee_stress=False,request_id=None)`、`list_backtest_jobs()`、`get_backtest_state(job_id)`、`stop_backtest(job_id)`、`set_backtest_watch(job_id|None,enabled)`、`open_backtest_chart(job_id)`、`set_backtest_capacity(value)`，返回统一`ok/reason`并保留明确身份。start先从ExperimentStore读取冻结修订，固定合约保留当前查询/到期预检，连续不做单月份查询。模拟继续走原ResearchSession。

- [ ] 写未知job、伪造run、模式注入、非bool参数和目录穿越输入拒绝，断言不能误停唯一其他任务。旧无job研究调用只有明确唯一对象时兼容；多个回测或模拟/回测同时存在时返回需选任务，不能猜测目标。
- [ ] 写A→B→A观看切换，旧订阅停、新代号生效、旧响应拒绝；完成的快跑任务直接打开离线结果，未收到柱的失败任务只显示结束原因。只有一个可见LiveResearchView，关闭它不停止计算。
- [ ] 写Workbench关闭通知覆盖任务池、模拟、行情及图形服务；第二实例持锁时给出“已有工作台管理回测”的明确状态，不向用户误报Python环境损坏。新入口中`freeze_support()`只在主模块执行，导入worker不建窗口。
- [ ] 跑`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_jobs_bridge.py -q`确认RED。
- [ ] 接入管理器和明确job绑定。与实际账户相关的旧模拟权限、账户锁、退出确认沿用，不从backtest参数开放paper/live。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_jobs_bridge.py tests/test_research_bridge.py tests/test_continuous_bridge.py tests/test_workbench.py tests/test_workbench_entry.py tests/test_credentials.py -q`，预期全部PASS。
- [ ] 提交`feat: expose explicit backtest job controls to workbench`。

### Task 9: 可继续编辑的多实验任务页面

**Files:** 新增`qf/web/research-jobs.js`、`tests/research_jobs_node.js`；修改`qf/web/research.js`、`qf/web/research-form.js`、`qf/web/research-results.js`、`qf/web/index.html`、`qf/web/style.css`、`tests/test_research_ui.py`。

**Interfaces:** `QfResearchJobs.create(root,api,{onSelect})`返回`refresh(),select(job_id),selected(),dispose()`；组件只管任务卡/容量/选中身份。research.js保持独立editorRef与editorDraft，任务选中不自动form.render。运行/停止/观察全部传明确job_id；模拟页面继续用原单任务接口。

- [ ] 写Node断言：A运行时新建/复制B并改周期，编辑按钮不受A.running锁定；提交冻结B修订；切换A/B不覆盖B草稿，不调用start或重复认证。按钮“双击”复用一次request_id，只创建一项。
- [ ] 写不同任务独立进度、预热/等待/保存标签、stop按钮带任务名；停止B发送B编号而非全局当前对象；页面隐藏/观看关闭只取消订阅。容量下调不提示已停止已有任务。
- [ ] 写迟到任务列表和图形绑定响应不能把A账户放到B，快跑完成点图打开离线结果，压力任务卡有父任务/费用倍率，比较使用冻结配置，页面不合计独立资金收益。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_ui.py -q`确认新脚本RED。
- [ ] 实现编辑/观察分离和显式任务控制。保留品种中文名、价格单位及已有响应式布局，不重做行情分屏。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_ui.py tests/test_research_terminal_state.py tests/test_research_jobs_bridge.py -q`，预期全部PASS。
- [ ] 提交`feat: edit and switch experiments while backtests run`。

### Task 10: 真实窗口、旧结果与多进程操作验收

**Files:** 新增`tests/parallel_workbench_smoke.py`、`tests/parallel_workbench_browser.js`、`tests/test_parallel_workbench.py`；更新`tests/research_workbench_smoke.py`、`tests/research_workbench_browser.js`、`tests/continuous_workbench_smoke.py`、`tests/continuous_workbench_browser.js`、`tests/test_research_workbench.py`、`tests/test_continuous_workbench.py`，使合成验收使用可导入子进程探针、内存凭证和临时目录。

**Interfaces:** 复用任务6离线worker和任务7管理器，不注入真实认证，不向公共桥接暴露调试入口。图形测试串行，两个回测子进程在同一图形测试内部真实重叠。

- [ ] 写真实WebView2流程：A运行→创建B不同周期/品种→A/B进程重叠→切换账户与保护→停止B但A历史时间继续→A完成→复制比较→确认退出→无凭证重开复盘。外层断言returncode=0及`PARALLEL_WORKBENCH_OK`。
- [ ] 写节点核对：首笔3301/3284等合成例子、初始/当前止损确实绘制、光标账户不穿越未来、合法0、费用跨日；快速切换期间帧/账户不得串；后台失败不出现永久等待空图。
- [ ] 写父管道断开/子进程崩溃/满队列退出/过时PID归属测试，记录只清理探针所属子进程，不能结束用户软件进程。当前代码和旧CLI/模拟/单窗口测试继续通过。
- [ ] 运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_parallel_workbench.py -q`确认RED。
- [ ] 做所需小范围连接修复，保持任务/账户/图形契约。
- [ ] 串行运行`.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_parallel_workbench.py tests/test_research_workbench.py tests/test_continuous_workbench.py -q`，预期全部PASS。
- [ ] 本机只读核对`20261019T123253-6101ebafbf8d`：用只读SQLite/临时一致快照验证161条成交、80笔完整、已存权益/累计费及3284保护可展示，缺失字段明确未记录，业务文件哈希/manifest不变。该资料不可用时用合成等价记录并明确未做真实文件核对，不把用户结果提交Git。
- [ ] 提交`test: verify parallel research and legacy trade inspection`。

### Task 11: 性能报告、说明与最终交付

**Files:** 更新`docs/research-paper-guide.md`、`docs/requirements.md`、`CLAUDE.md`；新增`docs/superpowers/reports/2026-10-19-parallel-backtest-verification.md`；无需新增产品依赖。

- [ ] 更新点击指南：当前实验与观察任务、默认2/可调1—4、快跑/观看、停止/退出含义、日内/累计费、初始/当前保护、旧缺失字段，以及后续组合研究边界。CLAUDE只加短索引，不复制整套设计。
- [ ] 用任务5探针在固定输入各重复3次，记录单任务快跑/观看、两任务串行/并行时长与分阶段耗时、不同PID和区间重叠、结果指纹；无改善如实报告瓶颈，禁止通过关闭持久化或未来数据检查达标。
- [ ] 运行`.\tools\check.ps1`及`git diff --check`，最终代码全部通过；若在隔离worktree，之后合回实际D盘时核对干净分支并验证整合结果。报告真实测试数量，不预填一个必须达到的计数。
- [ ] 使用最有能力的可用审查模型进行一次新鲜整体审查：重点看跨任务隔离、凭证、旧证据完整性、末段/窗口保护、停止和父子退出；不并行派发重复整体审查，保留未判断的联网/实际性能边界。
- [ ] 按实际影响分级，在一次TDD修复轮次内处理重要审查问题，跑相关回归及项目`tools/check.ps1`，全部通过后提交修复；无重要问题则记录无需修复，不空改。
- [ ] 向用户提供本机联网步骤：原入口重开→两项不同品种/周期分钟回测→切换资金/止损→独立停止→复盘比较。使用用户实际日期，权限/流控失败明确说明；未经实际联网不宣称完成，未经授权不做模拟委托或实盘。
- [ ] 提交说明和验证报告，按已沿用的交付方式保存至原仓库`codex/research-paper-loop`，不强推；核对本地与远程提交相同、工作区干净后报告。旧结果和archive完整保留。

## 计划自审与执行交接

- 覆盖：执行基准→1；账户/费用/兼容→2；保护依据和窗口→3；可观察界面→4；快跑及性能→5；进程/协议→6；容量/崩溃/退出→7；桥接与单模拟边界→8；编辑和任务切换→9；真实窗口和旧161条记录→10；完整检查/最终审查/联网边界→11。
- 类型：任务2account保持日内commission与额外累计字段；任务3protection统一为segments/pivots；任务5view_requested仅控制展示；任务6FrozenBacktest不含credentials，独立stream序号；任务7submit返回job_ids/selected_job_id，任务8桥接保持同名返回；任务9不靠全局当前任务控制。
- Review Focus五类均已落到对应RED测试；形成柱/CLOSE、不变OHLC、新旧证据、有效0、末段、迟到帧和异常退出均有明确断言。
- 当前为计划文件，不创建上述产品文件、不安装依赖、不启动账户。现有代码基线为498项通过，不当作新功能测试结果。
- 推荐沿用当前会话主代理逐任务直接实施，最后一次独立整体审查；任务共享账户、图形及进程协议，重复逐任务上下文交接成本较高。用户审阅本计划后按确认的执行方式启动，隔离工作区在执行阶段用using-git-worktrees技能处理。
