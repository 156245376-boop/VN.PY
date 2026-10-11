# 依赖与 CTP 版本记录

计划第 8 节要求钉死依赖并记录 CTP 版本号。**本文件是升级时唯一的对照依据** ——
`vnpy_ctp` 的 wheel 与 Python 小版本、CTP API 版本三者绑定,且 CTP API 因穿透式
监管一路 6.3.x → 6.7.x 变动。没有这份记录,升级出问题时无从判断变了什么。

版本选择的理由见 [ADR-0014](adr/0014-python-version-pinned-by-ctp-wheels.md)。

## 运行时

| 项 | 版本 | 备注 |
|---|---|---|
| Python | **3.13.11** (64 位 CPython, MSC v.1944) | 由 uv 安装至用户目录,不进系统 PATH |
| 解释器路径 | `C:\Users\15624\AppData\Roaming\uv\python\cpython-3.13.11-windows-x86_64-none\` | |
| 虚拟环境 | `.venv/`(项目内) | 与系统既有 Python 3.10.6 完全隔离 |
| 钉死方式 | `.python-version` + `pyproject.toml` 的 `requires-python = "==3.13.*"` | |

## CTP

| 项 | 取值 |
|---|---|
| `vnpy_ctp` | **6.7.11.4** |
| wheel | `vnpy_ctp-6.7.11.4-cp313-cp313-win_amd64.whl` |
| CTP API 版本 | 6.7.11(由包版本号前四段给出) |
| 穿透式监管采集库 | 随 `vnpy_ctp` 附带,位于 `.venv/Lib/site-packages/vnpy_ctp/api/` |
| 已验证 | `import vnpy_ctp` 成功(2026-08-30) |

**尚未验证**:实际 CTP 登录、采集库在 3.13 下能否正常加载。这两项要等 Phase 2
接入真实账户时才能确认 —— 采集库是 Windows 原生 DLL,其失效表现是登录被拒且
错误码不直观,通常 20:59 才发现(C3),故 Phase 2 须做启动前置检查(R1.1)。

## wheel 可得性矩阵(2026-08-30 实测)

决定解释器选择的核心事实。遍历 PyPI 全部发布版本,筛 `win_amd64`:

| Python | vnpy_ctp 最高版本 |
|---|---|
| cp310 | 6.7.11.3 |
| cp311 | **无** |
| cp312 | **无** |
| cp313 | 6.7.11.4 |

上界:vnpy 4.4.0 精确钉死 `PySide6==6.8.2.1`,该版本 wheel 为 `cp39-abi3`、声明
`requires_python <3.14`。故 **3.13 是同时满足"有 vnpy_ctp wheel"与"vnpy 依赖可装"
的最高版本**,3.14 会破掉 vnpy 的依赖。

## 已钉死的依赖

全部版本见 `pyproject.toml`。此处只记录**为什么不取最新**的几项:

| 包 | 钉死版本 | 最新版本 | 不取最新的理由 |
|---|---|---|---|
| `pandas` | 2.3.3 | 3.0.5 | vnpy 4.4.0 只声明 `pandas>=2.2.3`,语法上允许 3.0,但 vnpy 发布时 pandas 3.0 尚不存在,该组合未经上游验证。pandas 3.0 含破坏性变更 |
| `vnpy` | 4.4.0 | 4.4.0 | 当前最新 |
| `vnpy_ctp` | 6.7.11.4 | 6.7.11.4 | 当前最新且有 cp313 wheel |

其余(duckdb 1.5.5、pyarrow 25.0.1、polars 1.44.1、numpy 2.5.2、typer 0.27.2、
rich 15.0.0、pydantic-settings 2.15.0)均取实测时的最新版。

开发依赖:pytest 9.0.3、ruff 0.16.5、mypy 2.3.1、import-linter 2.14。

## Windows 中文环境的一处必需设置

`import-linter` 以系统默认编码(中文 Windows 上是 GBK)读取 `.importlinter`,
而该文件含中文注释,会抛 `'gbk' codec can't decode byte 0x80`。

**自动化统一调用 `tools/check.ps1`。** 该脚本固定设置 `PYTHONUTF8=1` 与
`PYTHONIOENCODING=utf-8` 后执行全部确定性检查；`.vscode/settings.json` 只改善交互式
终端体验,不再承担自动化正确性。若未来加入 CI 或提交钩子,也只调用该脚本。

不改用纯 ASCII 注释的理由:注释里写的是"为什么"(违反该契约会发生什么),这部分
必须让未来的审阅者读懂,不值得为绕开一个编码默认值而牺牲。

## 升级流程

1. 先查目标 Python 版本是否有 `vnpy_ctp` 的 `win_amd64` wheel —— 这是硬门槛
2. 查 vnpy 当前是否仍把 PySide6 钉死在 `<3.14` 的版本上
3. 在新 venv 中安装并 `import vnpy_ctp` 验证
4. **接真实账户验证登录与采集库**,不能只看 import 成功
5. 更新本文件与 `pyproject.toml`,追加 ADR 说明变更理由
