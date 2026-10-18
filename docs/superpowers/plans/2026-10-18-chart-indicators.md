# 可选技术指标与估算 VP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在当前四格天勤行情图中选择和叠加常用指标，编辑参数，显示可编辑固定区间和屏幕范围的估算 VP，并保存设置。

**Architecture:** 使用现有原生图表已核实的缓存，不新增行情会话。可信父页负责身份校验和计算调度，Python 纯计算复用天勤公式与 MarketProfile，子页适配负责坐标一致的图层及选区。指标设置独立原子保存，现有工作区文件格式保持不变。

**Tech Stack:** Python 3.13.11、TqSdk 3.10.2、MarketProfile 0.2.0、已锁定 pandas/numpy/scipy、原生 JavaScript、WebView2/pywebview。

**Spec:** `docs/superpowers/specs/2026-10-18-chart-indicators-design.md`（已确认）。用户已确认本会话顺序执行；八项实现、一次独立审查及其四项修复已完成，最终 tools/check.ps1 全通过（223 项测试）。

## Global Constraints

- 使用 `.venv-tqsdk`；依赖只通过 `tools/setup.ps1 -UpdateLock` 更新和安装，不裸 pip，不升级 SDK，不修改其安装资源。
- 常用指标直接调用 `tqsdk.ta`，简单均线为 `MA`，不是 SDK `SMA`；MACD 柱为 2×(DIFF−DEA)。
- 完整指标列表、默认参数、单位和参数边界以设计第 3、4 节为准；每种常用指标每格一个实例，VP 最多两个实例。
- 仅已有 K 线的研究显示；不自动接策略信号，不新增 TqApi、实盘入口、外部数据或付费下载。
- VP 始终标明“估算 · 按收盘价归集 · 当前周期”，不提供虚构主动买卖量或 Delta。
- 每次最多 20000 根输入、最多 1000 根预热柱、最多 512 个 VP 档；每档至少一跳且为整数倍；自动目标约 64 档。
- VP 宽度 10%–40%、透明度 10%–90%；周期参数 1–1000；均线最多 8 条；每档可选 1–10000 跳。
- 全局最多一个正在计算的任务；每格最多一个最新待处理请求；拖动约 250ms 合并，行情计算最多每格每秒两次。
- 数据缺失不补造、不静默截断；NaN 输出为空点；未收盘柱标注状态；错误局限于对应指标。
- 子页不开放 Python 桥接；认证对象、凭证、令牌和原始响应不进入计算、日志、配置或测试证据。
- 纳秒时间锚点跨桥接与落盘使用十进制字符串；测试使用临时配置和合成行情，不覆盖用户文件。
- 最终运行 `tools/check.ps1`，所有图形测试串行；联网行情验收和交易验收分开记录。

## Review Focus

1. 显示“同合约、同周期”时四格参数仍可能不同：结果须包含格及设置版本，任务 3、4、8 验证不串格。
2. 交易时间与 JavaScript 纳秒精度：夜盘/周末及日切分钟不得漂移，任务 2、7 用字符串锚点和既有交易日口径验证。
3. 窗口缩放和图层加入可能再次形成滚动条反馈：任务 5、8 在小数 DPI、大窗口及四格多副图下持续采样。
4. 市场平价/零量/坏柱及部分缺数据：公式可产生 NaN，但图中不能画假零或完整 VP，任务 1、7 验证隔离错误。
5. 用户在计算或保存中切换/隐藏格并马上退出：迟到结果不能恢复旧视图，最后有效设置不能丢失，任务 2、3、8 验证。

## 文件与责任

| 文件 | 责任 |
| --- | --- |
| 新增 `qf/indicator_catalog.py` | 有限指标白名单、初值、参数及输出描述 |
| 新增 `qf/indicator_calculation.py`、`qf/volume_profile.py` | 官方公式薄适配、VP 库薄适配；纯计算、不创建会话 |
| 新增 `qf/indicator_store.py` | 独立配置验证、原子保存、坏文件保护 |
| 新增 `qf/indicator_jobs.py` | 单工作线程、每格最新待处理任务、状态及结果回收 |
| 修改 `qf/workbench.py` | 配置和计算的可信桥接、关闭时清理 |
| 新增 `qf/web/indicator-state.js`、`indicator-panel.js`、`indicator-controller.js` | 纯设置状态、面板、保存与计算协调 |
| 新增 `qf/web/native-indicator-data.js`、`native-indicator-render.js`、`native-vp-range.js` | 已核实缓存导出、主/副图绘制、固定 VP 选区 |
| 修改 `qf/web/native-labels.js`、`native-tools.js`、`qf/window_host.py` | 适配路由、共享坐标与手势、注入；不扩展子页权限 |
| 修改 `qf/web/chart-pane.js`、`chart-workspace.js`、`app.js`、`index.html`、`style.css` | 格入口、消息身份、受控刷新、统一退出及局部布局 |
| 修改 `pyproject.toml`、`uv.lock`；新增 `docs/third-party-notices.md`、`docs/chart-indicators.md` | 锁定桌面依赖、保留许可、实际使用和验收说明 |

只按此功能拆分文件，不整理无关模块。下列接口返回均为白名单普通字典/数组，不返回 SDK 对象。

## Task 1：可验证的指标与 VP 计算

**Files:** 上表计算/目录文件、依赖与许可文件；新增 `tests/test_indicator_calculation.py`、`tests/test_volume_profile.py`。

**Interfaces:** `indicator_catalog() -> dict`、`validate_item(raw: object) -> dict`；`calculate_indicators(request: dict) -> dict`；`calculate_volume_profile(rows: list[dict], settings: dict, price_tick: float) -> dict`。
输入柱为 `{id, time_ns, open, high, low, close, volume, close_oi}`；结果包含 `series`、`profiles`、`issues`、`calculation_start_ns` 和预热说明。
每个序列保留 `item_id`、输出名、单位以及按柱编号/时间对齐的数值；NaN 转为 null。VP 输出价格档范围、手数、总量、比例、POC 和完整范围说明。

- [x] **1. 写失败测试。** `test_ma_is_simple_not_sdk_sma`：收盘 `[1,2,3,4]`、MA(3) 的适配输出断言 `assert values == [None, None, 2, 3]`；`test_official_indicator_parity` 参数化核对所有 11 种官方公式、尤其 MACD 柱值；`test_flat_or_missing_data_does_not_fabricate_zero` 验证平价、NaN、坏柱和单项失败隔离。
- [x] **2. 写 VP 黄金样本测试。** `test_profile_conserves_volume_and_bins_by_close`：一跳 0.5、收盘 `[10,10.5,10.5,11]`、手数 `[2,3,5,10]`、每档一跳，档量 `[2,8,10]`，总量 20，POC 11；覆盖 0.2 报价边界、并列最大量、零量、负量、512/513 档、20000/20001 柱与无效参数。
- [x] **3. 运行并确认失败。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_indicator_calculation.py tests/test_volume_profile.py -q`；应因新接口不存在失败，不以未安装解释器当成功的失败。
- [x] **4. 安装与实现最小适配。** 将 `MarketProfile==0.2.0` 加入 `desktop` 依赖组，执行 `.\tools\setup.ps1 -UpdateLock`；先验证导入和黄金样本，再接官方函数。无法通过时停止 VP、保留证据并报告，不替换算法或升级原依赖。锁文件仅允许新增包的必要变化。
- [x] **5. 复验并提交。** 使用 `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_indicator_calculation.py tests/test_volume_profile.py -q`；全部通过后核对依赖差异和许可，提交 `feat: 复用天勤公式与现成VP计算库`。

## Task 2：独立设置状态与原子保存

**Files:** 新增 `qf/indicator_store.py`、`qf/web/indicator-state.js`、`tests/test_indicator_store.py`、`tests/indicator_state_node.js`；修改 `tests/test_chart_workspace_ui.py` 添加 Node 包装。

**Interfaces:** `default_indicators() -> dict`、`validate_indicator_config(raw: object) -> dict`、`IndicatorStore(root: Path).load() -> dict`（返回 `config,issue`）、`.save(config: dict) -> None`；浏览器 `QfIndicatorState.defaults()`、`.reduce(current, action)`、`.validate(config)`。
根为 `{schema:1, panes:{"pane-1":{items:[]}, ...}}`。项字段固定为 `id,type,visible,params,style,height`；固定 VP 的合约和区间放 `params.range`，其中时间为十进制字符串。默认每格 volume/oi 启用，其他项未加载。

- [x] **1. 写失败测试。** `test_defaults_and_roundtrip` 核对四格及 volume/oi，保存后 `assert store.load()['config'] == config`；`test_bad_file_is_preserved` 验证坏文件不覆盖；`test_atomic_failure_keeps_old_file`；`test_ns_strings_roundtrip_without_precision_loss` 使用相差 1ns 的大时间值。Node 验证增删均线、修改参数、最多两个 VP、保持格间独立、顺序/副图高度与样式范围。
- [x] **2. RED。** 运行 `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_indicator_store.py -q` 和 `node tests/indicator_state_node.js`，确认接口缺失的预期失败。
- [x] **3. 实现。** 复用 Task 1 验证接口，保存至独立 `chart-indicators.json`；有限字段、严格布尔/整数、颜色只允许十六进制颜色值；原子写入失败清理临时文件。固定选区跨合约标为需重选，跨周期保留时间。
- [x] **4. GREEN。** 重跑上述命令；再跑 `tests/test_chart_workspace.py`，证明原 schema=1 的布局验证和恢复未变。
- [x] **5. 提交。** `feat: 保存每格独立指标设置`。

## Task 3：可信桥接与有界计算任务

**Files:** 新增 `qf/indicator_jobs.py`、`tests/test_indicator_jobs.py`；修改 `qf/workbench.py`、`tests/test_workbench.py`。

**Interfaces:** `IndicatorJobs.submit(request: dict) -> dict` 返回 `{ok,job_id,reason}`；`.poll(job_ids: list[str]) -> dict`；`.close() -> None`。桥接提供 `get_indicators()`、`save_indicators(config)`、`submit_indicator_calculation(request)`、`poll_indicator_calculations(job_ids)`。
请求身份固定为 `pane_id,generation,chart_revision,settings_revision,symbol,period`，另含 Task 1 输入、所需时间范围及 price_tick；结果逐项回传同一身份。状态为 queued/running/ready/error/superseded，错误只返回业务原因。

- [x] **1. 写失败测试。** `test_one_worker_latest_pending_per_pane` 用可控计算函数验证 `assert max_active == 1`、旧待处理被替代及四格公平推进；`test_result_identity_is_not_shared_between_panes`；`test_close_discards_pending_and_rejects_new_jobs`；桥接拒绝未知字段、非法类型、过大输入和未知指标，并验证认证对象不会进入纯计算。
- [x] **2. RED。** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_indicator_jobs.py tests/test_workbench.py -q`，确认新接口的预期失败。
- [x] **3. 实现。** 仅调用 Task 1、2 接口。单守护工作线程和有界结果记录；拒绝 NaN/Infinity 输入，保留 null 输出；不缓存无限旧 job。关闭先拒绝/清除待处理，计算完成后不再向已关闭界面发布；不阻塞现有行情线程或 UI 线程。
- [x] **4. GREEN。** 重跑任务测试，并核对现有关闭确认与清理时间上限保持原样。
- [x] **5. 提交。** `feat: 隔离并限制指标计算任务`。

## Task 4：原生缓存取样与版本协议

**Files:** 新增 `qf/web/native-indicator-data.js`、`indicator-controller.js`、`tests/indicator_protocol_node.js`；修改 `native-labels.js`、`chart-pane.js`、`window_host.py` 和 Node pytest 包装。

**Interfaces:** 子页 `QfNativeIndicatorData.snapshot(chart, request) -> object`，返回经过历史核验的柱、可见时间、数据版本和范围完整性。父页 `QfIndicatorController.create(options)` 返回 `.configure(paneId, settings)`、`.onMessage(event)`、`.setVisible(paneId, visible)`、`.flush()`、`.dispose()`。
新增消息仅为 `qf-indicator-config`、`qf-indicator-data`、`qf-indicator-result`；沿用 Task 3 身份，并带请求序号、数据版本。配置/结果从父到子，数据从子到父，不透传任意命令或 SDK 字段。

- [x] **1. 写失败测试。** 验证伪造 source/origin、旧 generation/图表版本/设置版本、旧数据结果和重建 iframe 的消息全被拒绝；同合约同周期不同参数不串格。验证隐藏格无新计算、250ms 合并及同一格每秒最多两次，相同版本不重复提交；柱编号和时间不变但 close/volume 改变时仍更新数据版本及指标。
- [x] **2. RED。** `node tests/indicator_protocol_node.js`，另跑既有 `tests/test_chart_workspace_ui.py` 确认新协议不破坏旧消息处理。
- [x] **3. 实现。** 从已确认的 `mainSeries.data` 和真实编号取样，不向 SDK 新增订阅。可见范围加最多 1000 根真实预热；固定 VP 必须完整覆盖。多项所需柱取并集，不能在 20000 上限外静默截取：常用指标窗口可用时继续，超限/缺数据的 VP 单独返回 issue。此任务只将已创建的数据脚本注入到 `native-labels.js` 之前；绘图及选区脚本分别在 Task 5、7 创建后加入注入列表，不提前引用不存在的文件。
- [x] **4. GREEN。** Node 与 pytest 包装通过；模拟断线/坏历史时撤掉不可信指标但保留原行情错误提示；更换参数或关闭格后迟到结果无效。
- [x] **5. 提交。** `feat: 对齐原生行情缓存与指标版本`。

## Task 5：主图叠加与独立副图

**Files:** 新增 `qf/web/native-indicator-render.js`、`tests/indicator_render_node.js`、`tests/native_indicators_smoke.py`；修改 `native-tools.js`、`native-labels.js`、`window_host.py` 与图形 pytest 包装。

**Interfaces:** `QfNativeIndicatorRender.attach(chart)` 返回 `.apply(result, settings)`、`.clear(itemId)`、`.dispose()`；只在子页内部访问 chart。`QfNativeTools` 增加 `.setIndicatorPriceExtent(chart, extentOrNull)`，由现有自动/手动价格域逻辑消费，不另包一套纵轴控制。

- [x] **1. 写失败测试。** Node 检查时间/价格映射、null 点不跨段连线、主图指标在自动域中可见而手动域不被抢回、不同量纲独立轴、隐藏一项不清除其他项。VP 的量 2/8/10 对应长度 20%/80%/100%，颜色暖度单调，左右方向正确、零量不绘制；透明度 45% 对应绘制 alpha=0.55。
- [x] **2. RED。** 运行 `node tests/indicator_render_node.js` 和新 WebView2 离线测试；失败原因应是图层/接口缺失。
- [x] **3. 实现。** 复用原生实际时间和价格映射；项目拥有的绘制层置于普通画线下，不拉伸 canvas。副图共享横向范围、独立纵轴，volume/oi 合并板内各自标单位且不重复显示原生默认量图。副图最小高度 120 CSS 像素，新增后触发真实尺寸重绘而非替换 iframe。
- [x] **4. GREEN。** 真实 SDK/WebView2 合成行情测试同时显示 MA+BOLL+MACD+RSI，调整价格/副图/账户分界、切周期、缩放窗口；验证横轴对齐和 canvas 实际尺寸，加入与既有画线同时显示的场景。
- [x] **5. 提交。** `feat: 显示可叠加主图与独立指标副图`。

## Task 6：格内指标面板与设置恢复

**Files:** 新增 `qf/web/indicator-panel.js`、`tests/indicator_panel_node.js`；修改 `chart-pane.js`、`chart-workspace.js`、`app.js`、`index.html`、`style.css`、`tests/workbench_smoke.py`。

**Interfaces:** `QfIndicatorPanel.create(root, {onChange,onSelectRange,onLocateRange})` 返回 `.open(paneId, config)`、`.close()`、`.dispose()`；配置使用 Task 2，计算/保存协调使用 Task 4，异步保存复用现有串行合并模式。

- [x] **1. 写失败测试。** 通过实际面板新增 MA/EMA 周期、修改 MACD 参数/颜色/线宽，加载两个 VP，隐藏/删除/恢复默认；错误参数保留旧结果。验证面板仅修改目标格，品种联动不带走其他格参数，重新打开恢复顺序和副图高度。
- [x] **2. RED。** Node 面板测试及 `tests/test_workbench.py` 中对应 GUI 用例失败于新增入口/操作缺失。
- [x] **3. 实现。** 每格增加中文“指标”按钮和局部面板；只列已确认 14 类。参数输入先校验后提交；样式改动无需重新计算公式；面板不挤压或遮挡原工具栏，关闭/失焦正确回收监听器。默认 volume/oi 保持原观察方式。
- [x] **4. GREEN。** 使用临时配置核对保存成功/失败提示、坏文件保护、重新打开恢复，以及隐藏格再显示时恢复其设置，iframe 地址和已有画线不变。
- [x] **5. 提交。** `feat: 添加每格指标选择与参数面板`。

## Task 7：固定 VP 选区、范围编辑和数据说明

**Files:** 新增 `qf/web/native-vp-range.js`、`tests/vp_range_node.js`；修改 `native-tools.js`、`native-indicator-data.js`、`indicator-panel.js`、`indicator-controller.js` 和 `tests/native_indicators_smoke.py`。

**Interfaces:** `QfNativeVpRange.attach(chart, {onChange})` 返回 `.begin(itemId)`、`.setRange(itemId, range)`、`.cancel()`、`.dispose()`；`range={symbol,start_ns,end_ns}`。通过 `qf-vp-range-change` 回报，使用 Task 4 相同完整身份；面板接收后走 Task 2 保存。

- [x] **1. 写失败测试。** 选两点、拖端点和直接输入时间均得到相同完整柱区间；测试周五夜盘/周一日盘、小时切分钟、相差 1ns 的边界；Esc/失焦取消未提交编辑并恢复左键平移，已提交区间不丢。
- [x] **2. 补范围质量测试。** 固定选区离开屏幕仍固定；换周期保留时间且标新计算周期；换完整合约进入需重选；只返回一部分缓存、内部缺柱、超过上限及无成交量时只暂停该 VP，不冒充完整结果。
- [x] **3. RED。** `node tests/vp_range_node.js`；WebView2 场景先失败于选择/编辑能力缺失。
- [x] **4. 实现并 GREEN。** 与现有绘图模式互斥；复用现有交易日/柱区间映射，保存纳秒字符串。面板支持区间定位，复用已有历史定位/取消机制；数据未到时不画假柱。悬停显示档位、手数、占比、估算周期；实现 POC 开关、左右、分档、宽度/透明度，冷热不表达买卖方向。
- [x] **5. 提交。** `feat: 添加可编辑区间与屏幕范围估算VP`。

## Task 8：完整联调、稳定性和交付

**Files:** 修改 `app.js`、`workbench.py`、`tests/workspace_stability_smoke.py`、`workspace_lifecycle_smoke.py`、`window_close_smoke.py`、`tests/test_workbench.py`；新增 `docs/chart-indicators.md`；更新 `CLAUDE.md`、需求及设计/计划实施状态。

**Interfaces:** 统一退出先停止指标采样/新任务、等待配置保存（沿用现有 2 秒等待上限），再释放父/子页控制器；桥接 `.close()` 属于现有关闭生命周期，不新增退出按钮或第二次确认。

- [x] **1. 写失败场景。** 同合约四格分别设不同 MA/MACD 参数，全部加载多个主/副图及 VP；快速切换品种/周期/隐藏/重开并在待计算或待保存时退出。新快照加入后确认受影响格更新、其他格设置和画线不丢，不创建第二个账户会话。
- [x] **2. 加入持续显示验收。** 在 1280×820、1800×1050、2540×1320、小数 CSS 边界及普通/整体/单格放大下，操作副图高度和图表/账户分界；收敛后每组至少 60 次采样，不能仅等到瞬间 ready。证据只记录白名单身份、尺寸、版本和状态。
- [x] **3. RED→GREEN。** 先观察新联调断言的预期失败，再只补齐保存/退出/生命周期集成。真实 WebView2 测试串行，子页无 Python 桥接；取消退出保留视图，确认退出正常结束。
- [x] **4. 最终检查。** `.\tools\check.ps1` 全通过；核对 SDK demo/web 135 项原版资源与依赖锁、`git diff --check`、无凭证/结果文件进 Git。运行离线测试不能宣称账户实时行情或策略有效。
- [x] **5. 交付记录。** 说明指标初值、VP 收盘价归集限制、OBV/预热起点、缺数据提示、保存与实际验收范围。用户本机联网验收如需凭证，由 Windows 已有安全保存渠道处理，不在聊天中索取。提交 `feat: 完成指标与估算VP联调验收` 并推送当前功能分支。

## 计划自审与执行交接

- [x] 设计的公式、指标目录和 VP 库复用由 Task 1 覆盖；参数状态与持久化由 Task 2、6 覆盖。
- [x] 数据质量/范围/精度与陈旧结果由 Task 1、3、4、7 覆盖；轴、图层和多指标由 Task 5 覆盖。
- [x] VP 时间编辑、样式、提示由 Task 5、7 覆盖；四格、保存、退出与持续稳定由 Task 8 覆盖。
- [x] Review Focus 五类风险各有对应行为测试；没有引入通用交易框架或额外账户权限。
- [x] 用户审阅本计划并选定执行方式。

推荐本会话顺序执行全部任务，最后由一个独立审查者审查整条分支：这些任务共享身份协议、坐标和保存生命周期，顺序实施便于保持接口一致。
也可选择逐项子代理实施和逐项独立审查；该方式每任务和每审查都会增加一次上下文。
用户已选本会话顺序开发，结束后进行一次独立审查。实现及全套离线检查已完成，提交推送随最终审查收尾。
