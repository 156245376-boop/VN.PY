# 当前项目地图

个人国内期货策略研究项目，基础能力使用天勤 TqSdk。
当前阶段：首次快期模拟只读连接及数据就绪已核对；历史回测和模拟委托待联网验收。
需求入口：`docs/requirements.md`。

| 路径 | 用途 |
| --- | --- |
| `pyproject.toml`、`uv.lock` | 新路线依赖及可复现版本 |
| `.venv-tqsdk/` | 当前环境，Python 3.13.11 / TqSdk 3.10.2 |
| `启动天勤.vbs`、`tools/workbench_entry.py` | 双击启动独立 WebView2 工作台，隔离环境并验证 |
| `qf/workbench.py`、`qf/window_host.py`、`qf/web/` | 可信桌面桥接、窗口与中文页面 |
| `qf/market.py`、`qf/market_session.py`、`qf/workbench_store.py` | 中文目录、只读行情与本机自选 |
| `qf/credentials.py` | Windows 安全保存快期凭证，两窗口共用，可忘记；密码不进项目文件 |
| `tools/gui_entry.py` | 保留的原研究窗口入口 |
| `qf/gui.py`、`qf/desktop.py` | 内存凭证、后台运行、停止和结果展示 |
| `qf/catalog_gui.py`、`qf/native_catalog.py` | 天勤现成功能目录、示例只读查看与资源核对 |
| `tools/setup.ps1` | 锁定安装，隔离旧环境变量 |
| `tools/check.ps1` | 封存完整性、环境身份、依赖与开发检查 |
| `tools/run.ps1` | data-check、backtest、paper；模拟默认观察 |
| `qf/` | 共用信号、实验记录、应用保护和 SDK 薄适配 |
| `experiments/rb-demo.toml` | 公开实验参数，不含凭证 |
| `results/` | 本机 SQLite、CSV、报告，Git 忽略 |
| `tools/environment_probe.py` | 不创建会话的解释器与 SDK 验证 |
| `tools/native_inventory.py` | 原生组件及 demo/web 资源清单，不创建会话 |
| `tools/verify_archive.py` | 验证封存包，按需在工作区外恢复 |
| `tests/` | 当前工具与环境保护测试 |
| `archive/README.md` | 封存包用途、校验和恢复入口 |

统一操作：`tools/setup.ps1`、`tools/check.ps1`。
旧 `.venv` 原地保留，不用于当前安装与运行。
旧需求、代码和 ADR 均已封存，默认不读取；过渡方案和实施记录不属于日常必读资料。
官方组件与权限边界按需查 `docs/tqsdk-native-kit.md`，不必为日常开发加载全部示例。
桌面工作台已核对本机目录/末次报价/K线显示与放大，开盘实时更新仍待验收。后续目标见需求末节。
连接灯、缺数据说明与报价单位按需查 `docs/market-data-display.md`。
历史覆盖、年份定位与数据异常保护按需查 `docs/history-integrity.md`。
价格轴、分隔条与右键画图按需查 `docs/chart-interactions.md`。
自适应布局、独立分屏、联动、共享画线与布局恢复按需查 `docs/chart-workspace.md`。
可选主图/副图指标、参数保存和估算 VP 按需查 `docs/chart-indicators.md`。
双均线实验、阶梯保护、回测比较与成交复盘的点击说明见 `docs/research-paper-guide.md`。
新实验入口在现有工作台“策略与参数 / 回测与比较 / 模拟运行”；旧研究窗口继续保留固定样例。
新版使用确认波峰／波谷动态止损、真实回测进度与可选运行图；旧实验只读复制升级，操作仍见上述指南。
新建研究默认版本3历史主力连续，可跨年回测并串行平旧开新、延续原R；固定月份与模拟保留版本2。
连续实现集中在qf/continuous_*.py及web/continuous-replay.js，复盘按窗口读取；账户多年权限仍待联网核对。
并行回测任务池、独立工作进程和账户证据按需查`docs/superpowers/specs/2026-10-19-parallel-backtest-observability-design.md`；
任务卡与账户/止损观察的操作说明见`docs/research-paper-guide.md`第9节。
