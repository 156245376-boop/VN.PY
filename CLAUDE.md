# 当前项目地图

个人国内期货策略研究项目，基础能力使用天勤 TqSdk。
当前阶段：首次快期模拟只读连接及数据就绪已核对；历史回测和模拟委托待联网验收。
需求入口：`docs/requirements.md`。

| 路径 | 用途 |
| --- | --- |
| `pyproject.toml`、`uv.lock` | 新路线依赖及可复现版本 |
| `.venv-tqsdk/` | 当前环境，Python 3.13.11 / TqSdk 3.10.2 |
| `启动天勤.vbs`、`tools/gui_entry.py` | 双击启动中文窗口，隔离环境并验证 |
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
