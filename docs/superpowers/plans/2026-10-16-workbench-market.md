# 独立桌面窗口与中文主力行情实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可双击启动、窗口登录、按中文浏览国内期货及实时主力行情的独立工作台，预留已确认的研究与新闻区域。

**Architecture:** 本批新增独立 WebView 主窗口和只读行情会话；原 Tk 研究入口保留，旧回测/模拟流程不重构。
行情会话只持有 TqSim，读取目录、主连映射与选中品种 K 线；UI 通过白名单桥接接收不可变快照。
原生天勤图表在窗口内展示；目录、自选和页面状态由项目实现，不修改 SDK 资源。

**Tech Stack:** Windows / Python 3.13.11 / TqSdk 3.10.2 / pywebview 6.2.1 / WebView2 / 本地 HTML、CSS、JavaScript / pytest、Ruff。
pywebview 版本及 Python 要求已通过 PyPI 官方元数据核实，实际 WebView2 兼容性由 Task 1 验收。

**Spec:** `docs/superpowers/specs/2026-10-16-desktop-research-workbench-design.md`。

## Global Constraints

- 简体中文；先国内期货，品种中文名与代码并列；数据与权限以账户真实返回为准。
- 保留 Python 3.13.11 / TqSdk 3.10.2，不恢复 archive 或使用旧 .venv。
- 依赖只经 tools/setup.ps1 -UpdateLock 更新和锁定；统一 tools/check.ps1，不使用裸 pip/uv sync。
- 凭证仅窗口和后台当前进程内存；不进配置、URL、日志、桥接状态或结果文件。
- 只读行情会话显式使用 TqSim；本批不发送委托、不建立实盘入口、不改变既有模拟执行保护。
- 原生页面和本机服务仅监听 127.0.0.1；不向局域网或公网发布；不修改 SDK 打包前端。
- 独立窗口验收前保留现有入口；关闭窗口等待后台会话释放，不强杀正在运行的旧任务。
- 当前执行方式沿用本会话逐项实现，完成后一次独立复核，不逐任务派实现代理。

## 范围拆分与后续交接

本计划对应设计批次 1，可独立验收。其余目标保留，分别形成后续可审阅计划：

| 后续计划 | 输入与交付边界 |
| --- | --- |
| 策略、参数与回测复盘 | 复用本批桌面容器、品种选择和视图桥接；增加策略版本、实验表单、因果关联和持久 K 线复盘 |
| 实验比较与持续模拟 | 复用实验档案；增加复制、差异比较、模拟任务、账户状态和交易留存 |
| 新闻与自动事件规则 | 独立数据源接入；保存事件版本与接收时间，执行端开仓许可和挂单控制，不阻止减仓/平仓 |

批次 1 不把后三批做成可点击但无结果的假功能。研究首页保留导航位置和现有研究入口，
明确未接入状态；不显示虚构回测、收益、新闻或实时行情。金十授权核实不阻塞本批。

## 文件职责与接口

| 文件 | 职责 |
| --- | --- |
| `qf/window_host.py` | WebView2 主线程窗口、可信页面、关闭协调与原生图表视图 |
| `qf/market.py` | 中文目录、行情行标准化、数值/时间校验与查询过滤 |
| `qf/market_session.py` | 单后台线程拥有 SDK，只读目录、订阅、快照、停止和释放 |
| `qf/workbench.py` | UI 白名单桥接、状态快照、自选与旧研究入口协调 |
| `qf/workbench_store.py` | 脱敏目录缓存与自选；原子保存；损坏文件明确回退 |
| `qf/web/index.html`、`app.js`、`style.css` | 中文本机工作台，真实状态呈现和交互 |
| `tools/workbench_entry.py` | 复用原入口隔离、环境验证并启动新窗口 |
| `tools/gui_entry.py`、`启动天勤.vbs` | 旧入口保留；通过验收后 VBS 指向新入口 |
| `tests/test_market.py`、`test_market_session.py` | 标准化、主连映射、线程/SDK 边界及清理 |
| `tests/test_workbench_store.py`、`test_workbench.py`、`test_window_host.py` | 持久化、桥接、真实窗口离线验收 |

行情快照为 JSON 可序列化白名单，字段固定：
`status`、`catalog`、`rows`、`selected`、`chart_url`、`reason`、`heartbeat_seconds`。
目录行包含 `continuous/name/exchange/product`；行情行增加 `underlying/last_price/change_percent/volume/open_interest/quote_time/data_state`。
不可用数值输出 null，不把 NaN/Infinity 或原始 SDK 对象传给页面。

## Review Focus

1. 中文元数据暂缺、涨跌分母为零或 NaN：名称可回退代码，数值明确不可用，不伪造报价；Task 2 覆盖。
2. 快速翻页/切换品种导致旧请求晚到：最新选择胜出，订阅有界，不改变其他运行任务；Task 3/4 覆盖。
3. 登录或连接中关闭窗口：页面能显示收尾，等待关闭 API，原始认证异常不外泄；Task 1/3 覆盖。
4. 旧缓存来自上次交易日：缓存只作目录参考，不显示为实时价格；Task 2/4 覆盖。
5. 新闻或文档外链误进入有 Python 权限的页面：可信 UI 与外部页面隔离，无通用执行/文件接口；Task 1/4 覆盖。

---

### Task 1：验证独立窗口、原生图表与退出生命周期

**Files:** Create `qf/window_host.py`、`tests/test_window_host.py`；Modify `pyproject.toml`、`uv.lock`、`tools/setup.ps1`、`tools/check.ps1`、`tests/test_environment_setup.py`。

**Interfaces:**
- Consumes：原有环境验证与 locked 安装；`qf.desktop.allowed_chart_url(url)`。
- Produces：`run_window(page: Path, bridge: object, request_close: Callable[[], bool]) -> None`；
  `show_chart(url: str) -> None`，只接受已验证的本机地址。

- [ ] **Step 1：编写失败测试。** `test_requires_webview2_without_ie_fallback`：引擎不可用明确失败；
  `test_chart_rejects_external_address`：外网/含凭证地址不进入内嵌视图；
  `test_close_waits_for_session_cleanup`：关闭请求未完成时窗口不销毁，完成后正常退出。
- [ ] **Step 2：运行** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_window_host.py`，确认缺接口失败。
- [ ] **Step 3：补最小实现及依赖。** 新增 `desktop=["pywebview==6.2.1"]` 依赖组，setup/check 同步该组；
  经 `.\tools\setup.ps1 -UpdateLock` 安装；固定 `gui="edgechromium"`，不静默回退旧引擎。
  扩展已有安装脚本行为测试，确认 desktop 依赖组确实随安装/检查使用，环境恢复保护不退化。
  主窗口仅加载项目可信资源；原生图表视图不暴露应用业务桥接；外链走系统浏览器。
- [ ] **Step 4：运行定向测试及真实 WebView2 离线烟测。** 加载本地测试页、调用最小桥接、
  展示真实 SDK 本地 HTTP 图形资源（内存认证替身，无账户连接），关闭后端口与线程退出。
  无法在当前环境可靠内嵌时记录确切原因，不替换 SDK、不降低到 IE；解决后才标记完成。
- [ ] **Step 5：执行** `.\tools\check.ps1`，通过后提交 `feat: add isolated WebView2 window host`。

### Task 2：中文目录、行情行与自选持久化

**Files:** Create `qf/market.py`、`qf/workbench_store.py`、`tests/test_market.py`、`tests/test_workbench_store.py`。

**Interfaces:**
- Produces：`catalog_rows(raw_rows: list[dict]) -> list[dict]`；
  `quote_row(catalog: dict, quote: dict, *, connected: bool) -> dict`；
  `filter_catalog(rows: list[dict], text: str, exchange: str | None) -> list[dict]`。
- Produces：`WorkbenchStore(root: Path).load() -> dict`；
  `save(catalog: list[dict], favorites: list[str]) -> None`，只持久化目录和自选。

- [ ] **Step 1：编写失败测试。** `test_searches_chinese_code_and_exchange` 用“螺纹钢/rb/SHFE”检索同一手工夹具；
  `test_missing_name_and_nonfinite_prices_are_explicit` 校验缺名称、NaN、零结算价；
  `test_old_cache_contains_no_live_quotes_or_credentials` 检查持久化白名单；
  `test_corrupt_settings_is_reported_without_overwriting_original` 检查损坏配置可见且不被无声覆盖。
- [ ] **Step 2：运行** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_market.py tests/test_workbench_store.py`，确认新功能失败。
- [ ] **Step 3：实现标准化和存储。** 使用天勤 `instrument_name/exchange_id/product_id/underlying_symbol`；
  最新价和前结算可用时计算涨跌幅，否则 null。原子保存到 Git 忽略的 `data/workbench/`，不保存报价或凭证。
  数据状态区分尚未就绪、连接中断和已有行情；行情时间直接显示，休市不凭无新 Tick 判定断线。
- [ ] **Step 4：运行定向测试**，确认中文/代码检索、null 数值、旧缓存标识与写入中断保护通过。
- [ ] **Step 5：执行** `.\tools\check.ps1`，通过后提交 `feat: add Chinese futures catalog and watchlist storage`。

### Task 3：有界订阅的只读行情后台

**Files:** Create `qf/market_session.py`、`tests/test_market_session.py`。

**Interfaces:**
- Consumes：Task 2 目录和行情行；原有 `chart_address()` 与地址验证思路。
- Produces：`MarketSession(*, sdk=None)`；`start(user: str, password: str) -> None`；
  `set_view(continuous: list[str], selected: str | None) -> None`；`snapshot() -> dict`；
  `stop() -> None`；`running: bool`。快照为复制值，UI 不读取 SDK 活引用。

- [ ] **Step 1：编写失败测试。** `test_readonly_session_never_inserts_orders`；
  `test_latest_selection_wins_and_subscription_budget_is_bounded`；
  `test_main_mapping_changes_update_display_without_trading`；
  `test_stop_during_connect_closes_returned_api_and_masks_error`；
  `test_heartbeat_does_not_replace_quote_timestamp`。SDK 替身下单接口直接失败，真实时间/选中顺序用手工夹具。
- [ ] **Step 2：运行** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_market_session.py`，确认新接口失败。
- [ ] **Step 3：实现会话。** API 只在一个后台线程创建/使用/关闭，显式 `TqSim()`、`debug=False`、`disable_print=True`；
  查询 CONT 目录，订阅可见与自选并读取选中品种分钟线，所有变化通过 `wait_update()` 推进。
  初版活跃订阅预算为 100 个行情对象（含选中真实合约）；超预算明确反馈。
  SDK 无单品种退订时，以重新创建只读行情会话清理累计订阅，不触碰模拟账户会话。
  选择命令以递增版本合并，只处理最新请求；映射更新立即显示，绝不调用目标持仓或下单。
- [ ] **Step 4：运行定向测试**，确认异常收尾、数据时间、订阅预算及快速切换均通过。
- [ ] **Step 5：执行** `.\tools\check.ps1`，通过后提交 `feat: stream bounded read-only main-contract quotes`。

### Task 4：工作台桥接和中文页面

**Files:** Create `qf/workbench.py`、`qf/web/index.html`、`qf/web/app.js`、`qf/web/style.css`、`tests/test_workbench.py`。

**Interfaces:**
- Consumes：Task 1 窗口、Task 2 存储与过滤、Task 3 `MarketSession`。
- Produces：`WorkbenchBridge(root: Path, session: MarketSession)`，仅公开
  `login(user, password)`、`get_state()`、`set_view(symbols, selected)`、`set_favorites(symbols)`、
  `open_resource(key)`、`disconnect()`；各返回 `{ok: bool, reason: str}` 或白名单状态。
  资源 key 固定映射官方文档/旧研究入口，不能传任意路径、命令或模块名。

- [ ] **Step 1：编写失败测试。** `test_bridge_serializes_only_public_fields` 将假令牌混入后台替身并确认不外泄；
  `test_stale_selection_cannot_replace_current_chart`；`test_resource_keys_do_not_execute_arbitrary_commands`；
  `test_favorites_are_validated_and_survive_restart`；`test_closing_window_waits_until_disconnect_finishes`。
- [ ] **Step 2：运行** `.\.venv-tqsdk\Scripts\python.exe -I -B -m pytest tests/test_workbench.py`，确认功能缺失失败。
- [ ] **Step 3：实现桥接和页面。** 页顶状态、左侧导航、中间品种表与选中 K 线、右侧自选/新闻区域。
  首页研究入口保持可见；未接入研究表单用明确说明，提供旧研究入口，不制作假回测结果。
  表格中文/代码检索、交易所筛选、收藏、选中合约详情；显示主连与真实主力、数据时间和连接状态。
  实时列表每页 40 行，自选最多 50 项，选择与真实主力引用合并去重后纳入 Task 3 的 100 对象预算。
  登录提交后清空页面密码框，页面状态/缓存中不保留凭证；业务桥接只供可信主页面使用。
  新闻区域显示真实未接入状态和官方来源链接，不自动抓取网页或启用事件规则。
- [ ] **Step 4：离线真实窗口交互验收。** 用无账户服务替身检查中文搜索、切换/收藏、图形内嵌、
  断开/重连状态和关闭；每个窗口测试在独立进程运行，避免重复 Tk/Tcl 生命周期影响。
  检查默认 1280×820 及较小窗口下主要控件可达；不自动打开外部行情浏览器。
- [ ] **Step 5：执行** `.\tools\check.ps1`，通过后提交 `feat: add the Chinese desktop market workbench`。

### Task 5：启动切换、文档与最终验收

**Files:** Create `tools/workbench_entry.py`；Modify `启动天勤.vbs`、`README.md`、`CLAUDE.md`、`docs/requirements.md`、`tests/test_window_host.py`。

**Interfaces:** 新入口沿用原 `tools/gui_entry.py` 的环境变量隔离和 `verify_environment()`；
旧 `tools/gui_entry.py` 保留，桌面快捷方式仍指向原 VBS，VBS 在最终离线验收后才切换新入口。

- [ ] **Step 1：编写失败测试。** `test_new_entry_isolates_environment_and_uses_project_runtime`；
  `test_missing_webview_runtime_is_actionable_without_account_output`；
  `test_launcher_opens_workbench_and_retains_legacy_entry`。运行实际入口/受控子进程，不能只搜索脚本文字。
- [ ] **Step 2：运行定向测试**，确认入口尚未实现时失败。
- [ ] **Step 3：实现并更新文档。** 新增依赖随锁定安装；缺 WebView2 明确报告并提供官方安装入口，
  不擅自弹出安装器；已有运行中的旧窗口不终止。说明本批范围及后三批目标，不宣称已完成策略界面。
- [ ] **Step 4：运行** `.\tools\check.ps1` 与双击启动离线验收；一次独立完整分支复核。
  关键发现用复现测试修复；只有文案/边角建议记录后由用户选择，不混入本批。
- [ ] **Step 5：用户本机安全输入后联网验收**：中文目录实际返回、自选行情更新、真实主力映射、
  选中分钟图、关闭释放；休市时明确只能验收读取，不能声称已验收开盘实时更新。
  凭证输入不是让用户发送到聊天，离线验证不能替代此步。
- [ ] **Step 6：更新实施记录、提交并推送当前分支**，保留原远程分支。记录未完成的联网验收项，
  再进入下一批独立实施计划，不据第一批完成宣称九项目标全部完成。

## 实施前自检与交接

- 本计划覆盖设计第 2/3 节及第 10 节相应检查；第 4—8 节的业务功能由后续三批计划覆盖，范围未丢弃。
- `catalog/rows/selected/chart_url` 为共同字段；SDK 活引用、认证对象及账户原始响应不越过后台边界。
- 登录、选择、关闭等跨线程请求先序列化；不存在 UI 线程直接调用 TqApi 的路径。
- 默认沿用当前用户指定项目和分支；执行前记录 Git 工作区与基线，不擅自切走用户已打开的软件目录。
- 计划供用户审阅；用户已确认整体设计，但尚未审阅本文件。审阅后沿用本会话逐项实现方式。
