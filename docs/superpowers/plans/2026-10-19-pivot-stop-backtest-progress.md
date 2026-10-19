# 动态拐点止损与可视回测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复未启动却让用户等待的回测入口，按确认拐点动态定仓，并提供真实进度与可选交易图。

**Architecture:** 扩展现有版本化实验、纯风险计算与串行SDK运行。后台发布已提交的受限快照，复用锁定SDK图表资源进行增量展示；观看开关不进入交易计算，也不新增账户或行情订阅。

**Tech Stack:** Windows、PowerShell、Python 3.13.11、TqSdk 3.10.2、SQLite、TOML、pywebview/WebView2、原生JavaScript；不增加产品依赖。

**Spec:** [已确认设计](../specs/2026-10-19-pivot-stop-backtest-progress-design.md)

## Global Constraints

- 本轮扩展现有工作台、单实际合约回测和快期模拟，不建立新的交易框架。
- 默认左右各2根已完成K线确认，确认根数可修改；pivot_left与pivot_right可设1—50。
- 相等的高低点不构成本轮严格拐点；未形成有效拐点时等待，不猜测或自动改用固定跳数。
- 止损价在入场后保持该笔已冻结的价格，不随实际均价重新平移，后续仅可按阶梯收紧。
- 高级手数上限、保证金比例默认关闭；关闭后仍受本笔持仓目标、可用资金与SDK限制约束。
- 实际初始R按实际初始手数、实际均价与冻结止损价确定，入场结束后封存；1R／2R／3R沿用。
- 不自动截短用户区间、换合约、换精度或把十年请求当作单月份的完整十年回测。
- 观看开关不改变SDK数据订阅、信号、保护触发与成交计算，不额外连接账户。
- 只有结果保存和核对成功后才显示100%；失败不能变成完成。
- 旧版本配置／结果按原语义只读展示和比较，不改写TOML或历史风险记录。
- 沿用当前codex/research-paper-loop工作区、.venv-tqsdk和官方TqSdk技能，不杀用户进程，不读取archive。
- 图形测试串行、只用合成SDK和内存凭证；凭证与原始认证异常不进聊天、日志、实验或图表快照。
- 使用tools/setup.ps1安装、tools/check.ps1验收；真实账户联网验证另行记录，无实盘入口。

## Review Focus

1. 信号时刻恰好完成拐点确认，之后才送达旧报价／新成交：拐点只按确认时间可用，保护不倒退（任务2、3）。
2. 取消入场期间又有成交，或实际均价越过冻结止损：仍记入实际仓位，停止追加、确认取消后退出，不丢成交（任务3）。
3. 换品种／日期后旧合约查询迟到，同时双击运行：不能用过期选择或创建两次修订／运行（任务4）。
4. 收起／展开图表、浏览器断连及读取旧快照：计算不重启、消息不串实验、不暴露未来数据或重复加载（任务5、6）。
5. 周末／节假日起止、SDK结束哨兵及中间无数据：不误报正常休市为缺失，也不把实际覆盖不足标为100%（任务3、6）。

## 文件分工

| 文件 | 职责 |
| --- | --- |
| qf/research_config.py、qf/experiment_store.py | 版本2、可选限制、字段错误和明确升级副本 |
| qf/pivot_stop.py | 已确认拐点、冻结入场计划与风险预算定仓的纯函数 |
| qf/trade_risk.py | 实际成交更新、固定止损锚点与现有阶梯保护 |
| qf/research_progress.py、qf/research_coverage.py | 历史时间进度与请求覆盖的纯核对 |
| qf/research_runtime.py、qf/research_journal.py | 串行执行、持久证据、每轮结束后发布快照 |
| qf/research_session.py、qf/workbench.py | 有效查询、后台状态、受限快照与启动控制 |
| qf/research_live_view.py、qf/web/native-live-research.js | 不创建SDK会话的只读运行图服务与增量展示 |
| qf/replay_view.py、qf/web/native-replay.js | 提取共享静态资源装配／坐标层，保留静态复盘完整性检查 |
| qf/web/research-form.js、research.js、research-results.js、style.css | 中文表单、字段定位、真实进度与观看开关 |

---

### Task 1：版本2配置、字段错误与旧实验副本

**Files:** 修改qf/research_config.py、qf/experiment_store.py、tests/research_helpers.py、tests/test_research_config.py、tests/test_experiment_store.py；新增tests/test_pivot_config.py。

**Interfaces:**
- 保留RiskConfig的版本1字段及含义；新增冻结PivotRiskConfig，保留共同定仓／阶梯字段，去掉stop_ticks，新增stop_method='confirmed_pivot'、pivot_left、pivot_right、limit_lots:bool、limit_margin:bool。max_lots:int|None、max_margin_ratio:Decimal|None；开关关闭时可为空，启用时必须有效。
- ResearchConfig.risk为RiskConfig|PivotRiskConfig；validate_research_config(raw:dict)->ResearchConfig接受严格版本组合(1,1)/(2,2)，拒绝混合、未知和凭证字段。版本2TOML可省略关闭上限的空值，读取时只对这两个已知可选字段补None，其他缺字段仍报错。
- ResearchValidationError(ValueError)：code:str、field_errors:dict[str,str]，全部内容来自白名单；validate_contract_request(continuous:str,start:str,end:str)->dict只校验查询字段，返回ISO日期字符串。
- migrate_to_pivot(config:ResearchConfig,*,name:str)->ResearchConfig产生2/2副本，左右2/2，保留共同参数；旧有上限显式保留为已启用以免静默放宽，并向用户说明。新建实验上限默认关闭。
- ExperimentStore.copy(...,name:str,upgrade_to_pivot:bool=False)->dict；升级时新ID、parent和新版本明确，原字节不变。版本1运行只由旧工具／兼容测试保留，新工作台入口只读，复制升级后才允许运行。
- tests/research_helpers.py新增pivot_config_data()->dict，为后续统一版本2夹具，金额仍为测试数据。

- [ ] **Step 1：写失败测试。** `test_v2_optional_caps_roundtrip`断言关闭上限的TOML重读后`risk.max_lots is None`且schema/strategy均2；开启上限却缺数值时`assert 'risk.max_lots' in exc.field_errors`。`test_legacy_copy_upgrade_preserves_original_bytes`断言原文件字节未变、parent正确、左右2/2且保留旧上限。覆盖bool冒充数字、NaN、混合版本、未知字段、固定手数超已启用上限；版本1原有测试保持原含义。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_pivot_config.py tests/test_research_config.py -q`；预期版本2／新接口尚不存在导致失败。
- [ ] **Step 3：实现上述接口。** 不自动迁移加载中的配置，不向界面返回原始解析异常。公开JSON的空值与TOML省略要往返一致，实验修订仍不可变。
- [ ] **Step 4：绿测。** 同上并加入tests/test_experiment_store.py；预期全部通过，旧period=15样例未变。执行git diff --check并读输出。
- [ ] **Step 5：提交。** 仅暂存本任务Files内实际变更；`git commit -m "feat: 添加拐点止损实验版本与明确校验"`。

### Task 2：无未来数据的拐点、动态手数与实际风险

**Files:** 新增qf/pivot_stop.py、tests/test_pivot_stop.py；修改qf/trade_risk.py、tests/test_trade_risk.py。

**Interfaces:**
- 冻结Pivot(kind:str,price:Decimal,bar_start_ns:int,confirmed_ns:int,left:int,right:int)，kind仅low/high。
- latest_confirmed_pivot(rows:list[dict],*,side:int,left:int,right:int,as_of_ns:int,previous:Pivot|None=None)->Pivot|None。rows含datetime、end_ns及OHLC；先按end_ns<=as_of_ns过滤完成柱，按严格左右规则取最新；滚动窗口移除旧柱后仍可保留previous，但不能保留确认时间晚于as_of_ns的拐点。
- 冻结EntryPlan字段side:int、lots:int、reference_price:Decimal、stop_price:Decimal|None、pivot:Pivot|None、distance_ticks:Decimal|None、per_lot_risk:Decimal|None、planned_r:Decimal、margin:Decimal、reason:str。
- plan_pivot_entry(risk:PivotRiskConfig,spec:ContractSpec,*,side:int,reference_price:Decimal,pivot:Pivot|None,available:Decimal,startup_equity:Decimal)->EntryPlan。无效返回lots=0和受限原因，不搜索更旧拐点。预算手数向下取整，执行资金／最小手数与可选限制；固定手数不可承担时跳过。
- apply_entry_fill原签名追加entry_plan:EntryPlan|None=None；None保留旧固定距离分支。新版以冻结stop_price计算真实R，保护价只收紧；RiskState现有字段保持可解析旧数据，止损原始来源保存在EntryPlan／事件，不依赖已经上移的当前stop_price重算。
- pivot_stop复用trade_risk的ContractSpec；trade_risk对EntryPlan只做TYPE_CHECKING／延迟注解引用，避免运行时循环导入，不复制合约规格类型。

- [ ] **Step 1：写失败测试。** `test_pivot_requires_completed_right_bars`用最低价[9,8,5,7,8]、左右2/2，断言右侧末柱未完成时None，完成后price=5且确认时刻为末柱end_ns。覆盖镜像波峰、等价不确认、无拐点、形成柱极值、前缀逐柱与批量结果相同、未来柱修改不改变过去决定、previous未来时间拒用。
  `test_position_scales_with_stop_distance_and_optional_caps`以参考1000、乘数10、预算1000、资金100000、每手保证金3000，止损995断言20手、止损990断言10手，启用max_lots=5断言5手并解释；相反方向、少于一跳、最小开仓、无资金与固定手数分别覆盖。
  `test_fills_keep_frozen_stop_and_seal_actual_r`以原计划20手／止损995、实际均价1001断言止损仍995、实际R=1200；部分成交立即保护，封存后部分平仓不重算R，1R／2R档位不回退。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_pivot_stop.py tests/test_trade_risk.py -q`；预期新函数不存在或仍固定距离导致失败。
- [ ] **Step 3：实现纯函数。** 复用Decimal、ContractSpec和现有阶梯规则，价格须有效且按tick核实。实际成交越过止损仍须先保存成交／仓位，标记entry_stop_invalid交给运行层取消并退出，不能因抛异常丢成交。新版首次偏移超过第一档触发价差时明确跳过，等于时按触及保护价退出并测试；旧版保留原含义。跳空风险差异只如实报告，不宣称保证预算。
- [ ] **Step 4：绿测。** 同上并加入tests/test_ma_cross.py、tests/test_research_review_regressions.py；预期新旧均通过。
- [ ] **Step 5：提交。** `git add -- qf/pivot_stop.py qf/trade_risk.py tests/test_pivot_stop.py tests/test_trade_risk.py`；`git commit -m "feat: 按确认拐点价格计算仓位与实际R"`。

### Task 3：串行执行、真实进度、覆盖和完整快照

**Files:** 新增qf/research_progress.py、qf/research_coverage.py、tests/pivot_sdk.py、tests/test_pivot_runtime.py、tests/test_research_progress.py、tests/test_research_coverage.py；修改qf/research_runtime.py、qf/research_journal.py、qf/research_session.py、qf/research_results.py、tests/research_sdk.py。

**Interfaces:**
- BacktestProgress(start_ns:int,end_ns:int,*,clock:Callable)在research_progress.py；update(stage:str,*,current_ns:int|None=None,bars:int=0,fills:int=0,success:bool=False)->dict、snapshot()->dict。字段stage、current_ns、percent、completed_bars、fill_count、elapsed_seconds、last_advance_age_seconds、finished；ns传前端为字符串。实际时间单调，超区间SDK结束哨兵不作为行情日期；未保存完成percent<=99，success才100。
- assess_coverage(*,expected_days:list[str]|None,observed_days:list[str],issues:list[str])->dict(status:str,missing_days:list[str],reasons:list[str])；status为verified/incomplete/unknown。日历用同一api.get_trading_calendar(start,end)取得，读取其trading列，核对SDK返回覆盖的年份范围；日历不可核实则unknown，不用猜测的工作日代替。
- discover_contracts保留接口，白名单返回expire_datetime和已被SDK真实提供的上市起点（没有则None）。启动前用已知日期做范围校验；回放后按真实交易日归属核对expected_days与有效区间柱的observed_days，内部柱质量仍用现有summarize_history。覆盖缺失或unknown不能标作完整回测成功，须给出具体原因和实际已处理范围；无交易日为明确空区间原因。
- ResearchLoop维护每侧最近Pivot、冻结EntryPlan和版本分支。反转待执行时携带pending_signal与对应pending_pivot，后者只允许确认时间<=pending_signal.completed_ns；新交叉替换这两个值，等待平仓不能把信号之后新确认的拐点带回旧信号。开仓前原子记录入场计划／拐点依据与目标；guard.scope在本笔计划确定后设置ExecutionScope(max(1,plan.lots),True)，last_target仍强约束开仓。无计划时不允许委托；禁用高级上限不等于取消账户保护。
- ResearchJournal扩展白名单payload的entry_plan、pivot和progress；state中的entry_plan用于恢复核对，成交事件关联该笔计划。每轮完成全部成交／柱／权益写入后才生成view_snapshot并发布，结束清单继续覆盖相关state、事件与柱。
- execute_research追加view_progress:Callable|None=None；只发布受限已提交快照，不按观看开关选择交易逻辑。ResearchSession接收并保存最近500根柱、窗口内成交与保护事件（上限5000条，超量明确只展示最近内容，全部证据仍在SQLite），公开live_snapshot()->dict。
- view_snapshot字段run_id、revision(递增int)、as_of_ns、symbol、bar_seconds、config、contract_spec、quote、bars、ma_series、fills、risk_events、entry_plan、progress、terminal。contract_spec仅合约规格／成本业务字段；quote仅datetime、last_price、price_tick、price_decs、volume_multiple、instrument_name。增量发布最密每200ms，结束必须发布；SDK对象／认证原文不可进入快照。形成柱OHLC不可包含as_of之后的数据，形成柱的结束边界可晚于as_of但不得当作已完成。无成交也照常推进进度。
- tests/pivot_sdk.py提供sdk_for_pivot(scenario='normal')->替身SDK，复用现有账户／撮合夹具并补充真实确认拐点序列、ask/bid和交易日历；保留旧sdk_for()的版本1场景，不用替换纯信号函数来伪造成功。

- [ ] **Step 1：写失败测试。** `test_progress_is_actual_time_monotone_and_save_gated`断言区间中点50%、旧时间不回退、2038哨兵不显示、保存前<=99、失败不100，成功保存才100。`test_calendar_handles_weekends_holidays_and_missing_middle_day`构造含休市日历，断言休市不算缺失，漏一个真实交易日为incomplete，缺日历为unknown。
  `test_confirmed_pivot_entry_is_same_for_backtest_and_paper`对同一输入断言信号与EntryPlan相同；`test_entry_cancel_late_fill_and_price_beyond_stop`断言成交完整记录、旧任务取消确认后退出、不丢实际暴露。`test_same_time_pivot_confirmation_and_stale_quote`覆盖Review Focus 1。`test_frozen_initial_stop_survives_restart_check`断言缺计划或代码／配置不匹配时冻结，不重算旧计划。
  `test_live_snapshot_is_committed_and_has_no_future_or_credentials`逐次推进并断言每个bar／fill不晚于as_of、快照不可变、序号递增、窗口有界，SQLite成交条数不因展示上限减少。覆盖覆盖失败、空区间、缺权限、保存异常和双费各自进度。
  `test_entry_plan_and_target_commit_atomically`在计划／目标事务注入失败，断言两者均未应用，SDK没有收到开仓目标；成交事务继续保留原有去重与回滚测试。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_pivot_runtime.py tests/test_research_progress.py tests/test_research_coverage.py -q`；预期新接口／行为缺失导致失败，不能用真实认证探测。
- [ ] **Step 3：实现。** SDK仍订一次并wait_update推进，收盘／拐点用真实完成时间，参考价取当前有效多单ask_price1／空单bid_price1。旧报价不得推进手续费或退回保护；反转先平仓，真正允许反向入场时用待执行信号当时合资格的拐点、当前报价和资金重新核对；测试等待期间又确认一个拐点时旧信号不受其影响。部分入场期间计划冻结，实际R随实际初始量更新直到封存；非法成交价触发既有取消／核对／退出状态机。
  阶段分别发布连接、读历史、预热、执行、保存、完成；客户端可用墙钟展示阶段等待，但不假称历史已前进。回测行情时间停滞超过config.timeout_seconds明确失败；委托确认仍使用execution_timeout_seconds，模拟休市不能因回测停滞规则被误冻结。
  发布必须在一个完成的执行轮次之后；复盘快照由唯一写线程读取已提交记录／维护的不可变副本，服务线程不自行拼接不同时间的SQLite状态。finish必须在export、完整性核对和summary成功之后，清理失败保留未决状态，不发100%。
- [ ] **Step 4：绿测。** 同上并加入tests/test_research_runtime.py、test_research_review_regressions.py、test_research_execution.py、test_real_sdk_boundary.py、test_runtime_safety.py、test_research_results.py；预期旧问题不回归、无账户会话。
- [ ] **Step 5：提交。** 仅暂存本任务Files内实际变更；`git commit -m "feat: 接入动态止损执行与真实回测进度"`。

### Task 4：可操作表单、具体错误与受限启动

**Files:** 修改qf/workbench.py、qf/web/research-form.js、qf/web/research.js、qf/web/research-results.js、qf/web/style.css、tests/test_research_bridge.py、tests/research_form_node.js；新增tests/pivot_form_node.js、tests/test_pivot_bridge.py；修改tests/test_research_ui.py注册新Node测试。

**Interfaces:**
- QfResearchForm现有read/render不变；新增readContractRequest()->dict、showErrors(field_errors:dict)->void、setRunState(snapshot:dict)->void。新草稿默认2/2与拐点2/2；高级开关关闭时输入不必填，止损距离是只读计算结果。
- WorkbenchBridge.save_experiment/get_research_contracts/start_research失败均返回{ok:false,code,reason,field_errors}白名单，启动成功返回job_id并在实际创建记录后发布run_id。表单校验失败不产生虚假run；保存与启动失败分别显示。query_contracts请求拥有递增request_id，前端按当前品种／日期与请求代号接受结果。
- copy_experiment追加upgrade_to_pivot:bool=False透传任务1；界面版本1只读，按钮明确“复制为新版拐点实验”。新工作台拒绝直接运行版本1，但旧CLI不受影响。compare_runs比较策略版本／止损方式并显示规则不同的提示。
- WorkbenchBridge.get_research_live_snapshot()->dict仅返回当前后台实验快照，不接收客户端路径或任意run_id。后台mode仍仅backtest/paper，运行配置与凭证流保持冻结与隔离。

- [ ] **Step 1：写失败测试。** `test_missing_contract_points_to_field_without_creating_run`断言空symbol时field_errors含symbol、后台execute调用数0、没有新的结果目录。`test_contract_query_needs_no_risk_fields`断言只填品种／日期也能查询。`test_stale_contract_reply_and_double_click_cannot_start_twice`改变日期后回旧请求，断言不可运行；恢复有效选择后双击断言修订／运行各只一次。
  Node断言stop_ticks输入不存在，左右2/2、未有信号显示“等待信号后计算”、高级开关关闭不需数值，错误定位字段及aria提示；旧配置复制提示与版本差异明确，名称脚本文本只作文本。凭证／伪造mode／未知合约仍拒绝。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_pivot_bridge.py tests/test_research_ui.py -q`；预期新表单与错误协议尚缺导致失败。
- [ ] **Step 3：实现。** 运行按钮仅在当前查询／实际合约有效且无任务时启用，缺项给出附近的可执行动作。查询期间可编辑查询字段并立即作废旧选择，但后台仍只有一个查询线程；旧查询结束后才可重查。实际策略运行期间冻结执行表单。保留同步commandPending防双击；catch只显示受限业务错误，不能吞掉返回reason，不能展示未知异常原文。实际正在连接与未启动的状态分开；进度条显示历史时间比例、当前日期与等待信息，缺估计显示“暂无法估算”。观看开关是本机展示偏好，不参与实验策略参数比较。
- [ ] **Step 4：绿测。** 同上并加入tests/test_research_bridge.py、test_research_session.py、test_workbench.py、test_window_host.py；图形测试串行。预期全通过，已完成结果不因运行失败消失。
- [ ] **Step 5：提交。** 仅暂存本任务Files内实际变更；`git commit -m "fix: 明确回测启动校验与动态风险表单"`。

### Task 5：隔离的增量运行图与静态复盘衔接

**Files:** 新增qf/research_live_view.py、qf/web/native-live-research.js、tests/test_research_live_view.py、tests/live_research_render_node.js；修改qf/replay_view.py、qf/web/native-replay.js、qf/web/research.js、qf/workbench.py、tests/test_research_ui.py；必要时新增qf/research_chart_assets.py，仅提取当前复盘静态资源装配，不建立通用图表框架。

**Interfaces:**
- LiveResearchView(snapshot_provider:Callable[[],dict])：open()->str、close()->None；本机127.0.0.1高位端口，仅SDK静态资源／只读快照／离线兼容ws，无SDK账户、认证、下单或文件任意读取入口。open同一运行幂等，换run必须清掉旧绑定。WorkbenchBridge.open_research_live_chart()->dict返回ok/url/run_id/generation；generation是一次图表绑定的固定代号，与后台递增的快照revision分开，窗口退出关闭本服务，不关闭独立行情会话。
- GET /snapshot?after_revision=N返回最新已发布完整视图快照；无变化时{changed:false,run_id,revision}，不重传整段；不是每秒重新查询数据库。图表最近500根及有界事件的起点／显示限制须可见，结束后的完整历史仍通过已校验静态ReplayView打开。
- QfNativeLiveResearch.attach(chart,options)->{apply(snapshot),dispose()}；复用QfNativeReplay的坐标／成交层，MA由已处理前缀计算，仅重算最近显示窗口加均线预热长度，不反复扫描全历史。bar IDs与真实时间稳定映射。消息按origin/source/run_id/generation绑定，快照另按revision单调接收；传给共享静态覆盖层的revision使用固定generation，避免其把正常的新快照当成另一个图表绑定而拒绝。最多每200ms提交一次显示更新，旧revision丢弃，新增柱追加、形成柱替换，移出窗口只移除显示数据，不删SQLite记录。
- 页面选择观看时打开iframe；关闭仅隐藏／暂停展示订阅，重新展开读取最新快照，不重启运行或SDK。图表读取失败显示原因，后台进度继续；默认跟随最新，用户浏览时按时间锚保留视区。

- [ ] **Step 1：写失败测试。** `test_live_view_never_constructs_sdk_or_exposes_auth`禁止真实TqApi，验证可打开页面与只读快照、无交易端点／业务桥接。`test_live_snapshot_identity_revision_and_source_are_checked`断言换run／旧revision／错误origin拒绝，HTTP无变化不回传全部柱。`test_chart_consumes_only_processed_prefix`逐帧喂合成数据，断言未收到未来柱、均线与成交，停止／冻结时显示未完成，保存核对通过才切静态复盘。
  Node验证同一revision不重建图层、形成柱更新、500根滚动后成交时间仍正确，iframe展开／收起保持同一个运行，旧消息不覆盖新实验，原有静态复盘仍校验完整性。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_research_live_view.py tests/test_research_ui.py -q`；预期新服务／图层不存在导致失败。
- [ ] **Step 3：实现。** 使用任务3已发布的不可变快照；小范围提取ReplayView资源装配，保持静态open必须验证完成记录的原语义。运行页使用__qfLiveResearch启动标记；加载共享native-replay.js时不置__qfReplay，不触发静态/replay加载器。服务绑定创建时的run_id，provider已换run时明确拒绝旧页请求，不把新实验推入旧图。有效run的数据未就绪时只显示阶段等待，首个合法快照才初始化图表，不伪造价格／空柱；测试随后数据到达时同一iframe转为绘图。图表快照不调用api.get_*，不增加任何行情订阅；进度中明确计算日期与图表日期。图形字段与资金来源均属于本次运行，消息检查origin/source/run_id/generation及递增revision，结束清理有界等待。
- [ ] **Step 4：绿测。** 同上并加入tests/test_replay_view.py、test_native_history.py、test_native_tools.py、test_research_workbench.py；预期全部通过，无重复加载，静态复盘无凭证重开仍有效。
- [ ] **Step 5：提交。** 仅暂存本任务Files内实际变更；`git commit -m "feat: 添加回测过程增量K线与保护线展示"`。

### Task 6：真实窗口闭环、使用说明与最终审查

**Files:** 扩展tests/research_workbench_smoke.py、tests/research_workbench_browser.js、tests/research_graph_probe.js、tests/research_reopen_browser.js、tests/test_research_workbench.py；新增tests/test_pivot_research_acceptance.py；修改docs/research-paper-guide.md、docs/requirements.md、CLAUDE.md；审查记录存docs/superpowers/reviews/2026-10-19-pivot-stop-backtest-progress.md。

**Interfaces:** 使用前五任务的公开入口；所有GUI实例串行、临时目录、合成行情、内存凭证，不连接真实TqApi。新增验收输出PIVOT_RESEARCH_OK，保留现有关闭／重开验证。

- [ ] **Step 1：写失败测试。** `test_view_toggle_does_not_change_strategy_execution`同一输入两次运行，只切换观看，按入场周期／成交顺序规范化随机ID后断言业务信号、计划、成交、风险、费用与权益逐项相同，引用关系保持一致；run_id和墙钟不作为交易结果比较。`test_full_pivot_progress_flow_in_webview`覆盖空合约具体提示→只填查询字段→有效月份→默认2/2拐点→风险预算→回测可视推进→收起看进度→展开不重启→成交原因与初始止损→保存后100%→复制比较→关闭、第二进程无凭证重开。覆盖无成交但日期推进、资料未返回、缺日历／缺覆盖、保存失败、部分成交与拒单、停机保留暴露、960×680布局及一次确认退出。
- [ ] **Step 2：红测。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_pivot_research_acceptance.py tests/test_research_workbench.py -q`；预期集成缺口有具体失败，若功能均已接齐则用之前失败的真实边界证明测试有效，不制造无意义故障。
- [ ] **Step 3：补齐集成与教程。** 教程给出实际中文按钮、左右2/2确认示意、预算与实际R的区别、自动距离、可选限制、看图／不看图、停滞／失败定位、单合约日期覆盖及双费进度。明确分钟近似／Tick口径、1跳不保证覆盖费用、停止与平仓停止区别；旧实验升级提示与新旧策略不可直接比较收益的边界均说明。requirements分别记录已实现和未联网，地图只加短入口。
- [ ] **Step 4：最终检查与一次独立审查。** 运行`.\tools\check.ps1`，核实完整退出码、pytest数量、Ruff与资源／封存校验；git diff --check。按已保留的当前会话顺序执行方式，最终由一个新上下文审查员只读审查本轮base到HEAD，不再派实施代理、不并行GUI。重要问题先写复现测试再修复，在一次修复轮次后重跑全套；未联网不表述为实际账户已验证。
- [ ] **Step 5：提交与交付。** 仅提交本轮变更并推送origin/codex/research-paper-loop，不合并main、不创建PR。交付操作教程、离线证据与本机联网验收步骤；不自动启动模拟委托，密码只在本机窗口输入。

## 计划自审与交接

规格1—2对应任务4/6；3对应任务2/3；4对应任务2/3；5对应任务1/4；6对应任务3/4；7对应任务3/5；8对应各任务与任务6。Review Focus五项均有对应具名测试。
相邻接口核对：任务1的版本类型→任务2纯风险→任务3固定EntryPlan／发布快照→任务4白名单状态→任务5只读展示→任务6闭环；版本1与版本2通过明确分支兼容，不混用stop_ticks。
当前仅设计／计划文档。沿用用户已经选择的执行方法：当前会话顺序实施，最后一次独立审查，保留现有工作区。待用户审阅本计划后启动任务1。
