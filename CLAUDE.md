# 当前项目地图

个人国内期货策略研究项目，基础能力使用天勤 TqSdk。
当前阶段：完成旧成果封存与独立环境准备，尚未实现交易策略。
需求入口：`docs/requirements.md`。

| 路径 | 用途 |
| --- | --- |
| `pyproject.toml`、`uv.lock` | 新路线依赖及可复现版本 |
| `.venv-tqsdk/` | 当前环境，Python 3.13.11 / TqSdk 3.10.2 |
| `tools/setup.ps1` | 锁定安装，隔离旧环境变量 |
| `tools/check.ps1` | 封存完整性、环境身份、依赖与开发检查 |
| `tools/environment_probe.py` | 不创建会话的解释器与 SDK 验证 |
| `tools/verify_archive.py` | 验证封存包，按需在工作区外恢复 |
| `tests/` | 当前工具与环境保护测试 |
| `archive/README.md` | 封存包用途、校验和恢复入口 |

统一操作：`tools/setup.ps1`、`tools/check.ps1`。
旧 `.venv` 原地保留，不用于当前安装与运行。
旧需求、代码和 ADR 均已封存，默认不读取；过渡方案和实施记录不属于日常必读资料。
