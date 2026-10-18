# 自适应布局与行情分屏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 按用户确认的设计，由主代理在当前分支顺序实施；不并行运行 GUI 测试。

**Goal:** 主窗口缩小时不遮挡，同时支持最多四格的独立行情、周期研究、共享会话画线和布局恢复。

**Architecture:** 一个 MarketSession 线程拥有后台只读 TqApi；可见格各有独立原生 iframe、版本和绘制状态。纯配置、后台订阅、单格视图和多格协调分别负责自己的状态，父页通过已校验消息协调各格；账户区只有一份。

**Tech Stack:** Python 3.13.11、TqSdk 3.10.2、现有 WebView2/pywebview、原生 JavaScript/CSS、pytest 和既有 Node/真实 WebView2 离线测试工具。

**Spec:** `docs/superpowers/specs/2026-10-18-responsive-chart-workspace-design.md`（用户已于 2026-10-18 确认）。

## Global Constraints

- 不升级 SDK、不修改安装包资源，不恢复封存架构。
- 四格为当前上限，不提前建设通用停靠框架。
- 周期白名单：分时、1分钟、5分钟、15分钟、30分钟、1小时、日线。
- 品种联动默认关闭；各格保留自己的来源和周期。
- 各格就绪需要实际数据与实际绘制核对，不以 iframe load 或全局绿灯认定成功。
- 当前 MarketSession 使用 `TqSim()`；账户区明确写“本地模拟账户 · 行情窗口”。
- 画线只在父页会话内保存，不增加磁盘持久化；主连与真实月份合约隔离。
- 凭证仍由 Windows 保存，不进入布局、业务消息、日志或 Git。
- 安装用 `tools/setup.ps1`，验收用 `tools/check.ps1`；使用 `.venv-tqsdk`，不增加产品依赖。
- 本轮不新增委托或实盘入口，不自动连接，不把离线通过当作免费多屏权限或交易验收通过。
- 工作位置沿用已确认的 `codex/research-paper-loop`；提交只包含本轮明确文件，不移动用户窗口或杀旧进程。

## Review Focus

1. 窗口缩放后，CSS 宽度小于物理分辨率：表格只在自身滚动，导航、分页和侧栏仍可达（任务 1、9）。
2. 连续切品种、来源和周期，旧异步结果迟到：只能接收当前格、当前连接版本，其他格不重载（任务 3—6）。
3. 收到实际目录前恢复配置，或某格保存品种已失效：保留配置并提示，不能静默换品种或自动登录（任务 2、4、9）。
4. 同合约两格同时编辑或撤销：不回写较旧快照、不循环广播，未完成编辑可回滚（任务 7）。
5. 拖动时隐藏格、切页面、失焦或退出：结束拖动、取消定位和轮询；临时放大不能销毁页面（任务 5、6、9）。

## 文件职责与固定接口

| 文件 | 职责 |
| --- | --- |
| `qf/chart_workspace.py`（新增） | 工作区纯配置校验、默认值及原子存储，独立于 SDK |
| `qf/market_session.py` | 单线程后台连接、订阅预算、各格准备与独立状态 |
| `qf/workbench.py` | 可信桥接、配置保存、快照白名单和兼容单图调用 |
| `qf/market_account.py`（新增） | 同一 TqApi 账户数据白名单快照，不建立会话 |
| `qf/web/chart-state.js`（新增） | 纯前端布局、活动格、可见格及联动变换 |
| `qf/web/chart-pane.js`（新增） | 一格 DOM、加载、历史、消息验证和销毁 |
| `qf/web/chart-workspace.js`（新增） | 多格协调、分隔条、放大、保存队列及会话画线协调 |
| `qf/web/chart-drawings.js`（新增） | 按合约存储的会话图形和撤销版本，纯逻辑 |
| `qf/web/account-view.js`（新增） | 集中账户区的安全文本渲染 |
| `qf/web/app.js`、`index.html`、`style.css` | 市场页面、登录、自选和新组件装配，修复布局收缩 |
| `qf/web/native-labels.js`、`native-tools.js` | 原生周期、活动、生命周期与画线适配 |
| `qf/web/native-history.js`、`qf/window_host.py` | 尽量沿用；确需生命周期适配时修改，不复制历史校验实现 |

统一配置 `WorkspaceConfig` 为 JSON 可表示的字典：
`{schema:1, layout, active, linked:false, split:{column:0.5,row:0.5}, account_collapsed:false, panes:[PaneConfig×4]}`。
`layout` 枚举 `single/columns/rows/quad`；`active` 为稳定 ID `pane-1` 至 `pane-4`。
`panes` 数组保留格的位置顺序；双图取前两格。只在 layout 动作使活动格落在可见范围外时，
才把活动格放到首位、其余按编号取足；activate 动作不调整数组顺序，避免点选导致两个图换位。
`PaneConfig={id,continuous:null|string,mode:'actual'|'continuous',period:null|'close'|'1m'|'5m'|'15m'|'30m'|'1h'|'1d'}`。
`period:null` 表示尚未显式选周期，解析为来源默认值；`close` 使用一分钟数据、原生 `mainType='close'`。
`split` 仅接收有限数值，比例限定 0.1—0.9；实际显示再按格的最小尺寸约束，不回写临时约束结果。
只接受四个唯一固定 ID，不信任任意额外字段；目录存在前只核对合约格式，连接后核对实际目录。

前后端每格运行描述 `PaneRequest={id,continuous,mode,period,revision}`，`revision` 为正安全整数。
后台快照 `PaneState={...PaneRequest,status,symbol,duration,history,reason}`；`status` 为 `idle/loading/ready/unavailable`。
`symbol` 在映射未就绪时为 null；对外 `duration` 统一为纳秒，与原生消息一致，调用 Python SDK 时转换为秒。
格配置改变仅递增受影响格的 revision，普通轮询、激活和 resize 不递增；隐藏后重新打开以 source 身份隔离旧页面。
顶层 `generation` 在连接启动时递增，`chart_url` 在同一后台连接期间稳定。
数据消息 envelope 为 `{kind,pane_id,generation,revision,...白名单字段}`；身份不能仅凭 envelope 判断。

各任务中的运行命令从项目根目录执行。Python 命令统一加 `-I -B -X utf8`。
新增 Node 场景必须有 pytest 包装，沿用 `shutil.which('node')` 和现有超时、输出断言方式。

### Task 1: 修复主页面窄窗口遮挡

**Files:** Modify `qf/web/style.css`、`tests/workbench_smoke.py`、`tests/test_workbench.py`。

**Interfaces:** 保留现有 DOM ID 和单图桥接协议；新增测试辅助 `assert_layout_bounds(window)`，后续任务继续调用。

- [x] **Step 1:** 在真实离线工作台复现 960×680、1280×820 和 1440×900；新增 `test_workbench_layout_stays_inside_cards`，断言 `.market-card` 不穿过侧栏、分页在卡片边界内、表格滚动不增加页面 `scrollWidth`、登录控件不重叠。记录修改前矩形坐标。
- [x] **Step 2:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_workbench.py -k layout -v`，应在当前布局的边界断言处失败；不得用截图字符串代替坐标断言。
- [x] **Step 3:** 修复 `.main-column` 隐式列、网格子项、卡片和过滤栏收缩；侧栏在容纳不下时移下方，导航短窗口允许滚动。先不改图表协议。
- [x] **Step 4:** 重跑上述测试，再跑 `tests/test_workbench.py`；要求原有搜索、自选和图表测试仍通过，查看各尺寸截图。
- [x] **Step 5:** 只暂存本任务文件，检查 diff 后提交 `fix: 修复窄窗口行情区域遮挡`。

### Task 2: 固定工作区配置模型和本机存储

**Files:** Create `qf/chart_workspace.py`、`qf/web/chart-state.js`、`tests/test_chart_workspace.py`、`tests/chart_state_node.js`、`tests/test_chart_state.py`。

**Interfaces:** Python `default_workspace() -> dict`、`validate_workspace(raw: object) -> dict`、`ChartWorkspaceStore(root: Path).load() -> dict`（返回 `workspace,issue`）及 `.save(workspace: dict) -> None`；root 为 `data/workbench` 目录，文件名固定为 `chart-workspace.json`。
JS `QfChartState.defaults()`、`visibleIds(config)`、`reduce(config, action)`，均返回副本；action 包含 `activate/layout/choose/source/period/link/split/collapse-account`。

- [x] **Step 1:** 新增测试断言：默认单图、四个固定 ID、联动关闭；单图活动为 `pane-3` 时切到双图得到 `[pane-3,pane-1]`，点击 pane-1 后仍为 `[pane-3,pane-1]`；联动开关本身不修改品种，之后 choose 仅改可见格；首次空格继承当前品种和来源，period 仍为 null。
- [x] **Step 2:** 补存储断言：旧安装缺文件返回默认；重复 ID、NaN/Infinity、布尔比例、未知周期和额外凭证字段拒绝；损坏文件保持字节不变且后续 save 失败；原子替换失败保留旧文件；未知但格式合法品种可在离线保存。
- [x] **Step 3:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_chart_workspace.py tests/test_chart_state.py -v`，确认缺少上述接口导致失败。
- [x] **Step 4:** 实现上述纯接口和原子存储，固定保存文件为 `data/workbench/chart-workspace.json`。
- [x] **Step 5:** 重跑以上测试和 `tests/test_workbench_store.py`，要求全部通过且原自选文件没有变化。
- [x] **Step 6:** 只提交这些新增文件，提交名 `feat: 增加行情工作区配置与原子存储`。

### Task 3: 后台改为一个稳定会话准备多格数据

**Files:** Modify `qf/market_session.py`、`tests/test_market_session.py`、`tests/test_market_shutdown.py`；复用 `qf/history.py`。

**Interfaces:** `MarketSession.set_workspace(symbols: list[str], panes: list[dict]) -> None`；`snapshot()` 增加 `generation,panes,chart_url`。
保留 `set_view(symbols,selected,chart_mode='actual')` 作为现有单图调用薄包装；旧顶层图表字段从 `pane-1` 投影，直到前端迁移完仍跑既有测试。
周期解析复用任务 2 的纯规则；准备序列长度为日线 3000、其余 200，分时与 1m 共用同一序列。

- [x] **Step 1:** 扩展 FakeApi 支持各白名单 duration、逐 `(symbol,duration)` 的失败/延迟；新增测试 `test_four_panes_share_one_api_and_change_independently`，断言改 pane-2 后 `len(FakeApi.instances)==1`、地址不变、其他格 revision 和结果不变、相同 key 只准备一次、下单调用为零。
- [x] **Step 2:** 新增测试 `test_stale_pane_and_mapping_results_are_discarded`，覆盖读取期间修改请求、同品种主力映射变化；只影响对应实际合约格。`test_pane_failure_does_not_clear_other_panes` 断言日线失败不阻断分钟和报价。
- [x] **Step 3:** 新增 `test_capacity_rejection_keeps_previous_workspace`：按后台已订阅 symbol 与新增真实合约去重，总量不超过现有 100 保护上限，列表/自选/格需求全部计入；预检失败不部分应用、不重建会话。超过容量的异步映射变化保留原图并标明映射过期，不能把旧合约写成新主力。
- [x] **Step 4:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_market_session.py tests/test_market_shutdown.py -v`，确认新增场景在多格独立状态断言处失败。
- [x] **Step 5:** 实现 `set_workspace`，替换 `_serve_view` 的单选择退出逻辑为可更新格集合；SDK 对象仅在原线程使用。调整旧测试只针对被本需求改变的“换品种必须重建会话”假设，不删除历史质量或凭证断言。
- [x] **Step 6:** 重跑以上检查并全部通过；变更停止语义仍不能在 stop 后发布图表。
- [x] **Step 7:** 提交 `refactor: 保持行情会话并隔离多格数据状态`。

### Task 4: 桥接多格请求、恢复配置和可信快照

**Files:** Modify `qf/workbench.py`、`tests/test_workbench.py`。

**Interfaces:** `WorkbenchBridge.get_workspace() -> dict` 返回 `workspace,issue`；`save_workspace(workspace: dict) -> dict` 返回 `ok,reason`；`set_workspace(symbols: list[str], panes: list[dict]) -> dict` 返回 `ok,reason`。
`get_state()` 增加经过白名单过滤的 `generation,panes`；继续保留登录、自选、资源和兼容 `set_view`。

- [x] **Step 1:** 新增 `test_workspace_restore_never_connects_or_returns_credentials`、`test_workspace_requests_are_validated_and_atomic`，断言恢复仅读配置，合法四格请求到原 session、无重复 ID 和非法目录项、未知保存品种不自动替换。
- [x] **Step 2:** 新增 `test_pane_snapshot_is_bound_to_revision_and_generation`，输入伪造地址、错配合约、旧 revision、异常数值和带认证对象的 raw；输出不得暴露原对象或把旧历史挂到新格。旧 pane-1 兼容字段与新字段一致。
- [x] **Step 3:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_workbench.py -v`，确认新增测试因缺少工作区接口而失败。
- [x] **Step 4:** 实现上述桥接接口；存储失败返回明确中文提示，不清空目录、自选或当前浏览状态。
- [x] **Step 5:** 重跑任务 2—4 的 Python 测试并全部通过，新增错误输出中不出现 fake secret 或认证响应。
- [x] **Step 6:** 提交 `feat: 桥接并保存可信的多图工作区配置`。

### Task 5: 原生图表支持独立身份、周期与可取消生命周期

**Files:** Modify `qf/web/native-labels.js`、`qf/web/native-tools.js`；按需修改 `qf/web/native-history.js`；Modify `tests/test_native_labels_script.py`、`tests/native_tools_node.js`、`tests/window_smoke.py`；Create `tests/native_panes_smoke.py`、`tests/test_native_panes.py`。

**Interfaces:** 父页命令继续使用 `qf-chart-labels`、`qf-chart-command`，新增完整 envelope；子页报告 `qf-chart-ready/state/selection/activate/period/escape`。
`QfNativeTools.cancelInteraction() -> boolean` 取消编辑/绘图/临时定位并返回是否消费操作；`dispose() -> void` 清除本适配监听、计时器与定位请求。
只有宿主注入允许的父页可发命令，子页仍没有 Python 业务桥。

- [x] **Step 1:** 新增四个真实 SDK iframe 的离线场景：相同及不同合约/周期各自产生 `web_chart` 请求；改一格周期不改变其他三格的 symbol/duration 或页面实例。扩充 fixture 支持所有周期，阻断外部 WebSocket，不使用真实凭证。
- [x] **Step 2:** 新增测试断言 5m/15m/30m/1h 可从父页选择，分时与一分钟区分 mainType；原生选择反向报告正确的格和周期，父页选择确认不得回发成新用户动作形成循环。
- [x] **Step 3:** 增加断言：blur/隐藏/销毁取消定位和未提交编辑，Esc 有未完成操作先取消，否则发还原请求；每页最多一个周期状态上报计时器。
- [x] **Step 4:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_native_panes.py tests/test_native_labels_script.py tests/test_native_tools.py -v`，确认当前新身份协议和周期绑定失败。
- [x] **Step 5:** 实现 envelope 绑定、周期白名单和取消/销毁接口；隐藏重复原生程序标题、订阅侧栏与账户区时，以真实 Vue 布局尺寸重算图表，不简单裁切 canvas。
- [x] **Step 6:** 重跑上述检查和 `tests/test_native_history.py`，原有价格比例、120 分钟映射、年份和幽灵拖拽仍通过。
- [x] **Step 7:** 提交 `feat: 隔离原生图表身份与多周期操作`。

### Task 6: 装配单图、双图、四宫格和分隔条

**Files:** Create `qf/web/chart-pane.js`、`qf/web/chart-workspace.js`、`tests/chart_workspace_node.js`、`tests/test_chart_workspace_ui.py`；Modify `qf/web/app.js`、`index.html`、`style.css`、`tests/workbench_smoke.py`。

**Interfaces:** `QfChartPane.create(root, options)` 返回 `{update(context),post(command),setExpanded(value),dispose()}`，`options={id,onActivate,onChoose,onPeriod,onEscape}`。
`QfChartWorkspace.create(root, options)` 返回 `{update(state),choose(symbol),getConfig(),setVisible(value),dispose()}`，`options={config,onConfig,onView,onFavorite}`；`onView(panes)` 只发送可见格请求。
任务 7 通过此协调器连接画线存储；app 继续独占目录、报价、自选保存队列和登录，不把其实现复制到格内。

- [x] **Step 1:** 新增纯状态/DOM 边界测试：四种布局、活动格高亮、choose 只影响活动格、品种联动保留周期来源、单格自选绑定其品种、右键自选不切格；任意一格加载不显示其他格的 ready 数据。
- [x] **Step 2:** 新增消息攻击/迟到测试：错 source、origin、格 ID、generation、revision、symbol、duration，以及隐藏格消息，全部拒绝；正确消息只更新其格。单格更新不得修改其他 iframe 的 src；后台拒绝容量或配置时回滚本次提议，不把拒绝的配置保存为成功结果。
- [x] **Step 3:** 扩充真实 WebView2 测试验证分隔条在格外松开、单格和工作区分别放大、Esc 优先级、右键与画图模式不串台；恢复后原 frame、周期和图形仍在。
- [x] **Step 4:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_chart_state.py tests/test_chart_workspace_ui.py -v`，确认当前缺少独立控制器和布局行为导致失败。
- [x] **Step 5:** 实现单格控制器、工作区协调器并连接任务 4、5；原图表卡移动到整个行情组合区下方。临时放大隐藏使用样式而非销毁；setVisible 在任务 9 补充页面切换释放行为。
- [x] **Step 6:** 实现列/行分隔条，最小宽 340 CSS px、面板高 420 CSS px；pointer capture 配合遮罩跨 iframe 拖动，pointerup/cancel/blur 均清理；键盘方向键每次调整 0.02。小窗口局部滚动，比例存储原偏好。
- [x] **Step 7:** 重跑本任务测试、任务 1 的边界测试和工作台完整 smoke；全部通过并检查截图。
- [x] **Step 8:** 提交 `feat: 增加可调整的多图行情工作区`。

### Task 7: 同合约跨格画线同步与一致撤销

**Files:** Create `qf/web/chart-drawings.js`、`tests/chart_drawings_node.js`、`tests/test_chart_drawings.py`；Modify `qf/web/native-tools.js`、`native-labels.js`、`chart-workspace.js`、`tests/native_tools_node.js`、`tests/native_panes_smoke.py`。

**Interfaces:** `QfDrawingBook.create()` 返回 `{read(symbol),commit(symbol,baseVersion,drawings),undo(symbol,baseVersion)}`；结果为 `{ok,version,drawings}`，失败返回当前版本但不改状态。
`QfNativeTools.exportDrawings(symbol) -> array`、`applyDrawings(symbol,version,drawings) -> boolean`；应用远端快照不发布新的本地提交。
消息 `qf-drawings-commit/undo/state` 使用同一身份 envelope，symbol 需匹配已核实的本格合约。

- [x] **Step 1:** 新增测试：A 在小时图画完整两小时矩形，B 的分钟图同锚点覆盖 120 柱；A 编辑后 B 更新一次；B 撤销后 A 恢复到共同前一版本；实际合约与主连、其他品种完全隔离。
- [x] **Step 2:** 覆盖版本冲突、旧快照、远端同步回环、另一格编辑中的冲突回滚、删除/清除的统一撤销、新建/恢复隐藏格读当前会话图形。以有限载荷拒绝超出 200 个图形、错误类型、非法坐标和不完整锚点，父页总计最多保存 100 个合约的会话标记，达到上限明确提示而不逐出已有标记。
- [x] **Step 3:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_chart_drawings.py tests/test_native_tools.py tests/test_native_panes.py -v`，确认当前图形无法跨格同步及保护版本。
- [x] **Step 4:** 实现纯图形簿和 native commit/apply；预览留在本格、ID 使用全局不冲突的格前缀加计数。
- [x] **Step 5:** 重跑全部图形场景，确认未完成笔、历史定位、实际价格坐标和不填充休市柱的行为不变；父页重新连接可保留会话画线，关闭主窗口不保存。
- [x] **Step 6:** 提交 `feat: 同步多格研究画线并保护编辑版本`。

### Task 8: 集中显示一份准确标识的只读账户

**Files:** Create `qf/market_account.py`、`qf/web/account-view.js`、`tests/test_market_account.py`；Modify `qf/market_session.py`、`qf/workbench.py`、`qf/web/chart-workspace.js`、`index.html`、`style.css`、`tests/native_panes_smoke.py`、`tests/workbench_smoke.py`。

**Interfaces:** `account_snapshot(api, *, connected: bool, observed_at: str) -> dict` 仅在 MarketSession 线程调用；顶层字段为 `kind:'local_sim',connected,observed_at,summary,positions,orders,trades`。
`QfAccountView.create(root)` 返回 `{update(snapshot),setCollapsed(value)}`；折叠偏好经工作区配置保存。

- [x] **Step 1:** 用 SDK 文档和本机对象核实字段，写 `test_local_account_snapshot_contains_only_business_fields`：summary 仅 balance/float_profit/margin/commission/available，NaN 转 null；持仓、委托、成交只包含合约、业务 ID、时间、方向、开平、手数、价格和状态，排除账号、认证、私有字段及原始通知。
- [x] **Step 2:** 增加离线 UI 断言：四格下只出现一份“本地模拟账户 · 行情窗口”，空记录明确空状态；后台断线保留末次快照和原 observed_at，并标失效，不能把断线轮询时间当新账户数据时间。
- [x] **Step 3:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_market_account.py tests/test_market_session.py tests/test_workbench.py -v`，确认缺少集中账户快照导致失败。
- [x] **Step 4:** 实现读取和白名单渲染；只调用当前 api 的 get_account/get_position/get_order/get_trade，不创建 TqKq 或新会话，不调用任何委托接口。保留原生主图/成交量分隔交互，集中账户区的高度调整仍触发真实重绘。
- [x] **Step 5:** 更新离线 fixture 的白名单账户数据，重跑本任务测试及真实工作台 smoke；要求数值、账户折叠/展开和单份显示的断言全部通过。
- [x] **Step 6:** 提交 `feat: 集中显示行情窗口的只读本地模拟账户`。

### Task 9: 恢复、隐藏释放、退出与整体验收

**Files:** Modify `qf/web/chart-workspace.js`、`chart-pane.js`、`app.js`、`tests/workbench_smoke.py`、`tests/test_workbench.py`、`tests/test_market_shutdown.py`、`tests/window_close_smoke.py`；Create `tests/workspace_lifecycle_smoke.py`（由 `tests/test_workbench.py::test_workspace_lifecycle_in_real_webview` 子进程包装）；Modify `docs/requirements.md`、`docs/chart-interactions.md`、`CLAUDE.md`。

**Interfaces:** `dispose()` 可重复调用；布局保存队列单写入、只保留最新配置，未成功保存时不能显示“已保存”。已有 `window.qfPrepareExit()` 扩展到释放全部格，不改宿主确认对话框的授权与取消语义。

- [x] **Step 1:** 新增真实生命周期测试：quad→single→quad 重复三次，隐藏格前端连接计数归零、恢复获得新页面且会话画线恢复；单格放大不减少页面实例数；历史定位/拖拽期间隐藏、切页面、失焦均取消交互，迟到消息无效。
- [x] **Step 2:** 新增持久化 UI 测试：改活动格、周期、来源和比例后重启仍恢复，未连接不调用 login/start；模拟旧保存写入延迟、保存失败、损坏文件和当前目录移除品种，界面状态与提示符合设计。保存队列只提交成功版本，旧返回不能覆盖新配置。
- [x] **Step 3:** 新增退出测试：取消确认保留全部连接；确认后释放所有格、计时器、临时定位和后台会话，进程结束。使用测试自己创建的进程，不能终止用户现有软件。
- [x] **Step 4:** 运行 `.venv-tqsdk/Scripts/python.exe -I -B -X utf8 -m pytest tests/test_workbench.py tests/test_market_shutdown.py tests/test_window_host.py -v`，确认新增的释放、恢复或保存竞态场景失败，记录具体断言。
- [x] **Step 5:** 实现 `setVisible(value)`：离开首页/行情页时释放格页面，回到页面时由配置及会话画线恢复；实现控制器内部 `queueSave(config) -> Promise`，串行调用 `options.onConfig(config)`、合并尚未发出的中间版本、只接受成功确认。扩展幂等 dispose 和 qfPrepareExit，清理交互/轮询及消息处理；不自动改选失效品种。
- [x] **Step 6:** 重跑上一步测试；按 Task 1 尺寸加最大化做真实边界与截图检查。分别记录原生缩放或用 WebView2/CDP 的设备尺度与 CSS viewport 仿真，注明哪项是实际 100/125/150% DPI、哪项是仿真，不把仅改截图尺寸说成 DPI 验证。
- [x] **Step 7:** 运行 `.\tools\check.ps1`；要求退出码 0、pytest/Ruff/135 项 SDK 资源完整性通过，无账户连接。失败时按实际原因修复，只在代码变化或失败依据下重跑相应测试。
- [x] **Step 8:** 根据用户已有的本机只读验收授权，使用原凭证路径进行四格连接核对；记录各格实际权限、原生连接、数据时间与局部失败，禁止下单。若凭证不可用，给用户界面操作步骤，明确联网验收未完成，不在聊天索取密码。
- [x] **Step 9:** 更新文档区分“已实现/离线通过/联网通过”，补充四屏用法及已知限制；完成一次独立只读代码审查（执行阶段使用 requesting-code-review 技能，复用可用 reviewer，不并行实施），修复证实的问题并验证。
- [x] **Step 10:** 提交 `feat: 完成行情分屏恢复与生命周期验收`，按现有约定推送当前分支。

## 自审与执行交接

需求覆盖：设计 §3.1→任务 1；§3.2—3.3→任务 2、5、6；§4.1→任务 3、4；
§4.2→任务 4—6；§4.3→任务 7；§5→任务 8；§6→任务 2、4、9；§7—8→任务 5、9。
五项 Review Focus 均有归属任务，接口字段沿用本计划上方定义。

书面设计与本计划均已获确认；任务 1—9 已实施，独立审查两项问题已修复，最终 190 项测试通过。
执行方式沿用主代理在当前会话、当前分支顺序实施；无需再次选择多代理方式。
实施按任务从上到下执行，各任务先验证失败场景、再改实现、再验证和提交；结果见 `docs/chart-workspace.md`。
