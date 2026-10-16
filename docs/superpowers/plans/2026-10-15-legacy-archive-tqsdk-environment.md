# 旧项目封存与天勤环境切换实施计划

> **供执行代理：** 必须使用 superpowers:executing-plans（推荐本次采用）或
> superpowers:subagent-driven-development，按任务执行并更新复选框。

**Goal:** 可恢复地封存旧项目，移除其活动入口，交付独立、可复现且不登录账户的天勤环境。

**Architecture:** 旧工作树保存为一个带清单与校验的 ZIP，完整性验证后才切换活动文件。
新入口只保留当前需求和必要安全约束；天勤使用独立虚拟环境与新锁文件。
只留下一个小型封存验证工具，不开发通用备份系统或交易框架。

**Tech Stack:** Windows PowerShell、CPython 3.13.11、uv 0.9.25、TqSdk 3.10.2；
归档校验使用 Python 标准库，开发检查使用 pytest 9.0.3、ruff 0.16.5。

**Spec:** [已确认方案](../specs/2026-10-15-legacy-archive-tqsdk-environment-design.md)。

**Status:** 用户已批准主代理直接执行；三个任务已完成，独立复核发现已修复，最终门禁通过。

## Global Constraints

- 旧 .venv 原地保留，不改名、不卸载；新环境固定为 .venv-tqsdk，Python 3.13.11。
- SDK 初始版本固定为 tqsdk==3.10.2；天勤自身的 tqsdk-ctpse 等依赖正常锁定。
- 封存当前磁盘字节，包括所有未提交与未跟踪的旧成果，不能用 git archive HEAD 替代。
- 旧文件现有基线为 98 个、625,594 字节；执行时重新核实，变化先查明再继续。
- 封存包与源文件复验通过后才移出旧文件；同名包、恢复目标与移出目标均禁止覆盖。
- 不打包或移动 .git、虚拟环境、真实凭证、运行数据及未知文件；不递归清空仓库根。
- Windows 移出文件统一用 PowerShell Move-Item -LiteralPath；每个绝对路径先检查边界。
- 本阶段不创建 TqApi/TqAuth 会话，不取行情、不回测、不登录或下单；SDK 类只做导入。
- 所有新安装与最终检查显式使用新环境，不使用 --active、裸 pip、旧 qf 或旧激活状态。
- 本地 Git 缺少作者信息。提交失败时保留工作区并记录，不虚构作者、不修改全局身份，
  不把这个限制误报为封存或安装失败。当前分支为 codex/archive-tqsdk-env。

## Review Focus

1. 验包后用户又编辑源文件：移出前二次比对失败，保留变化，不把新内容当成已封存。
2. ZIP 路径穿越、重复成员、符号链接、缺失或多余成员：在任何解压写入之前拒绝。
3. 已有同名封存包或非空恢复目录：拒绝覆盖；空文件、点文件和中文路径可以完整恢复。
4. 终端遗留旧环境、Python 路径，或 uv 执行失败：目标仍是新环境，进程变量完整恢复。
5. SDK 导入成功但来自错误解释器或路径：最终检查失败，不能据此宣布天勤环境就绪。

## 文件分工

| 路径 | 操作与职责 |
| --- | --- |
| archive/legacy-vnpy-2026-10-15.zip | 创建；完整旧工作树、清单与 Git 状态证据 |
| archive/legacy-vnpy-2026-10-15.sha256 | 创建；包的外部 SHA256 |
| archive/README.md | 创建；用途、状态限制、校验与安全恢复命令 |
| tools/verify_archive.py | 创建；只读验包、按需安全解压，不含旧业务规则 |
| tests/test_archive_integrity.py | 创建；完整恢复、损坏与恶意成员的回归 |
| tools/setup.ps1 | 创建；隔离环境变量、初始化新锁、锁定安装 |
| tools/environment_probe.py | 创建；验证实际解释器与 SDK 身份，不创建会话 |
| tools/check.ps1 | 旧版封存后替换；封存、环境身份、锁、依赖及开发检查 |
| tests/test_environment_setup.py | 创建；安装入口失败恢复、环境身份与配置边界 |
| pyproject.toml、uv.lock | 旧版封存后替换；仅新路线与开发检查依赖 |
| AGENTS.md、CLAUDE.md、README.md | 旧版封存后替换；简短活动入口与操作命令 |
| docs/requirements.md | 创建；当前环境阶段与保留的后续目标 |
| .gitignore、.vscode/settings.json | 旧版封存后替换；忽略环境、切换解释器与检查范围 |
| 旧 src/tests/tools/docs/.kiro/conf 与 .importlinter | 按冻结清单移出；新文件与本次方案/计划不移出 |
| .python-version | 旧版保全后重新写入 3.13.11 |

### Task 1：冻结旧成果清单，验证封存工具

**Files:** 创建 tools/verify_archive.py、tests/test_archive_integrity.py；
冻结清单及一次性打包脚本存放在工作区外的独立临时目录，不成为活动模块。

**Interfaces:**
- verify_archive(archive_path: Path, expected_sha256: str) -> dict[str, int]。
- extract_verified_archive(archive_path: Path, expected_sha256: str, destination: Path,
  *, forbidden_root: Path) -> dict[str, int]。
- 成功报告含 file_count、source_bytes；失败抛出 ArchiveError(ValueError)。
- CLI：--archive、--sha256-file；可选 --extract-to。退出码 0 表示完整验证通过，
  非零表示拒绝；不提供覆盖选项。

- [x] **Step 1：执行旧 tools/check.ps1 并记录结果。** 普通用例应全部通过，
  8 个市场事实用例仍因原守卫明确处于待核对状态，不修改预期值。
- [x] **Step 2：冻结清单。** 保存旧门禁结果、HEAD、Git 状态、
  git diff --binary HEAD、排除表及逐文件路径/长度/SHA256 到工作区外。
  使用 git ls-files -z 与 git ls-files --others --exclude-standard -z 的并集，
  排除 docs/superpowers/；独立检查凭证和路径，确认当前仍是上述 98 个旧文件。
  在创建新工具前完成冻结，后续新增迁移文件单列为允许新增，不混入旧清单。
- [x] **Step 3：编写失败测试。** 用独立临时 ZIP，测试
  test_roundtrip_preserves_empty_hidden_unicode_files、test_corruption_is_rejected、
  test_unsafe_or_duplicate_members_are_rejected、test_member_set_mismatch_is_rejected、
  test_restore_refuses_workspace_or_nonempty_destination。
  对恶意 ZIP 传其真实整体哈希，确保测试确实验证成员检查而非提前因哈希不同而失败。
  核心断言如下，异常场景还须断言没有越界写入：

  ```python
  assert restored_bytes == original_bytes
  assert report == {"file_count": 3, "source_bytes": sum(map(len, original_bytes.values()))}
  with pytest.raises(ArchiveError):
      extract_verified_archive(bad_zip, correct_hash, destination, forbidden_root=workspace)
  ```
- [x] **Step 4：用现有解释器运行新测试，确认因工具缺失失败。**
  命令：.venv\Scripts\python.exe -m pytest tests/test_archive_integrity.py -q。
  此处旧解释器只服务迁移工具验证，不代表新 SDK 环境已经就绪。
- [x] **Step 5：实现上述接口。** manifest 使用 schema_version=1、entries 数组，
  每项为 path、size、sha256；源文件成员为 project/<path>。
  metadata/ 固定包含 manifest.json、git-status.txt、working-tree.patch、exclusions.json。
  校验完整成员集合、成员路径/类型、大小、逐文件哈希和整体哈希，再允许解压。
  拒绝绝对路径、盘符、反斜杠/上级路径、链接及重复名；恢复目标在工作区外且为空。
- [x] **Step 6：同命令重跑测试为通过，运行旧环境 Ruff 检查新增两个文件。**
  保留工具源码与测试，旧清单不因此改变。该任务不移出文件、不安装包；
  与 Task 2 一并提交，避免把尚未完成的切换记成完成。

### Task 2：制作可恢复封存包，切换活动入口

**Files:** 创建封存包、哈希文件、索引和 docs/requirements.md；替换根入口与配置，
按冻结清单移出旧文件；保留 Task 1 新文件及 docs/superpowers/。

**Interfaces:** 消费 Task 1 的两个验证接口和冻结清单；交付可恢复 ZIP、外部哈希、
简短新入口及不含旧模块的活动布局，供 Task 3 安装。

- [x] **Step 1：用一次性脚本制作包。** 对冻结文件先复验；用独占创建模式写新包，
  不覆盖任何已有文件。写入当前源字节与固定 metadata/，生成 .sha256 文件。
  再次发现旧清单变化或未知新增文件时停止，不刷新清单掩盖变化。
  先在独立演练目录预放同名包，要求脚本拒绝且原包字节不变，再制作真实包。
- [x] **Step 2：验证真实包。** 运行 verify_archive.py 验包，并用 --extract-to 解压到
  工作区外的新临时目录。除工具报告外，用冻结清单独立重算恢复文件哈希，要求路径、
  字节数与每文件哈希全部相同；记录包哈希与真实文件总数。
- [x] **Step 3：移出旧文件。** 先把一份只读恢复清单留在工作区外；逐文件再次比对，
  先在独立演练目录执行“验包后修改源文件”的用例，要求移出操作被拒绝、
  修改后的源文件保持原位；演练通过后才对真实旧文件继续。
  将旧文件 Move-Item 到工作区外、禁止覆盖的回滚目录。当前根路径和每个目标都先
  Resolve/校验为指定根内路径，不移动 .git、.venv、数据与新迁移文件。
  移出后只清理已核实的旧源码缓存及空目录；遇到未知文件保留并报告。
  若中途失败，依据清单将已移出的文件恢复原位；新旧字节冲突时保留双方并停止。
- [x] **Step 4：写新入口与最小配置。** AGENTS.md 只指向当前需求、检查命令、
  天勤技能及“不默认读取封存包”；CLAUDE.md 记录当前布局和环境，README 解释安装、
  检查与后续开户材料。docs/requirements.md 保留方案列出的交易目标与安全原则，
  当前验收只含封存和环境；不把双均线当成用户既定策略。
  pyproject.toml 使用 [tool.uv] package=false、requires-python="==3.13.*"，
  dependencies=["tqsdk==3.10.2"]，dev extra 固定 pytest==9.0.3、ruff==0.16.5。
  pytest 只发现新 tests/，pythonpath=["."]；Ruff 只检查新 tools/ 与 tests/。
  .python-version 写 3.13.11；不创建新的 src/ 或交易骨架。
- [x] **Step 5：完成索引与活动边界检查。** archive/README.md 链接 .sha256，
  写明旧系统未完成、市场事实待核对，以及工作区外恢复命令。
  .gitignore 忽略 .venv/、.venv-tqsdk/、缓存、凭证、/data/、/results/，不忽略封存包。
  编辑器解释器指向 .venv-tqsdk，移除旧 src extraPaths、旧 pytest 参数及自动发现；
  此阶段不启用应用调试配置。检查旧冻结路径只有明确被新入口替换的文件仍在原位，
  其余旧源码、旧需求与旧 ADR 均已退出活动树，Git 历史保持存在。
- [x] **Step 6：记录 Task 1/2 结果并尝试提交。** 仅包含本次完整转换的明确路径；
  不凭 git diff 里的删除数量判断数据丢失，必须以包及恢复校验为准。
  作者信息缺失时记录未提交，不修改作者配置，不阻塞后续本地环境准备。

### Task 3：安装隔离环境，完成无账户验收

**Files:** 创建 tools/setup.ps1、tests/test_environment_setup.py、新 uv.lock；
创建 tools/environment_probe.py；替换 tools/check.ps1，并补齐 README、CLAUDE 与环境实际状态。

**Interfaces:**
- setup.ps1 默认只做锁定同步；-InitializeLock 仅在根 uv.lock 不存在时允许生成初始锁。
  锁已存在时此开关必须失败，不提供默认升级或重锁。
- setup/check 均使用绝对 UV_PROJECT_ENVIRONMENT 与新解释器，退出码非零即失败。
- check.ps1 只检查，不安装、不登录、不更新锁。
- tools/environment_probe.py 提供 verify_environment(expected_environment: Path) -> dict[str, str]，
  身份不符时抛出 EnvironmentCheckError(RuntimeError)。CLI 为 --expected-environment，
  成功输出 JSON，失败非零退出；返回 python、executable、tqsdk、module_path 字符串字段。

- [x] **Step 1：新增环境保护回归，并先观察失败。**
  test_setup_restores_environment_on_uv_failure 把真实 setup 脚本复制到临时项目，
  用 PowerShell 函数替身 uv 返回 23；传入旧 VIRTUAL_ENV、PYTHONPATH、PYTHONHOME
  及 UV_PROJECT_ENVIRONMENT 哨兵值。要求替身确实调用、收到的是绝对新环境路径，
  脚本报告失败，四个变量存在状态和值全部恢复，旧环境没有创建/安装变化。
  test_initialize_lock_refuses_existing_lock 要求已有锁的字节不变且 uv 未执行。
  先用 .venv\Scripts\python.exe -m pytest tests/test_environment_setup.py -q
  运行这两个迁移保护用例；SDK 身份用例在安装后另加。
- [x] **Step 2：实现 setup.ps1。** 用 try/finally 保存并恢复上述四个进程变量，
  临时清除前三个；不打印其值，不改 PATH 或持久环境变量。
  -InitializeLock 分支先运行 uv lock --project <root> --python 3.13.11；
  然后运行 uv sync --project <root> --python 3.13.11 --locked --extra dev。
  每条原生命令后立即检查 LASTEXITCODE；不使用 --frozen 或 --active。
  PowerShell 脚本保持 ASCII，以兼容 Windows PowerShell 5.1；中文操作说明写入 README。
- [x] **Step 3：通过保护回归后实际安装。** 运行 .\tools\setup.ps1 -InitializeLock。
  成功应生成新 uv.lock 与 .venv-tqsdk；安装失败保留封存包与旧环境，修复已定位的问题，
  不自动切到旧环境或其他 Python，不宣称完成。
- [x] **Step 4：新增身份验证失败测试。**
  test_environment_probe_rejects_wrong_prefix 捕获目标环境路径后，用 monkeypatch
  将 sys.prefix 改为独立临时目录，要求 verify_environment 拒绝；
  test_environment_probe_rejects_wrong_sdk_path 将 tqsdk.__file__ 改为目标环境外路径，
  要求拒绝。两者均断言 EnvironmentCheckError，不修改磁盘中的 SDK。
  新环境以 -I -B -m pytest 运行这两个用例，先确认因探测模块缺失失败。
- [x] **Step 5：实现探测模块和只读 check.ps1。**
  运行真实封存验证、uv lock --check、uv sync --locked --check --extra dev，
  项目命令均带绝对 --project、--python 3.13.11 与 --no-python-downloads；
  uv pip check --python <新环境绝对 python.exe> --no-python-downloads。
  采用与 setup 相同的进程环境隔离及 finally 恢复。
  check 调用新 Python 的 -I -B 模式执行 environment_probe.py，
  verify_environment 验证以下条件，导入 TqApi、TqAuth、TqSim、TargetPosTask
  及 numpy/pandas/scipy，不实例化类：

  ```python
  assert sys.version_info[:3] == (3, 13, 11)
  assert sys.flags.isolated == 1
  assert Path(sys.prefix).resolve() == expected_environment
  assert sys.prefix != sys.base_prefix and site.ENABLE_USER_SITE is False
  assert importlib.metadata.version("tqsdk") == "3.10.2"
  assert Path(tqsdk.__file__).resolve().is_relative_to(expected_environment)
  ```

  同命令重跑身份验证用例为通过；检测标准写成独立断言，不照抄实际输出。
  用目标解释器运行官方技能 check_environment.py，要求 ready 且版本、路径一致。
  项目门禁独立检查上述条件，不依赖固定的个人技能安装路径。
- [x] **Step 6：运行最终门禁。** 新 tools/check.ps1 使用新解释器运行新 pytest、
  Ruff、真实包验证及上述环境/依赖检查，全部通过；git diff --check 通过。
  对照迁移前记录核对旧 .venv 的 pyvenv.cfg、已安装发行版元数据及 editable 指向未被修改。
  回滚目录保留至这些检查通过；此后仅清理本次创建、路径已核实的临时副本。
- [x] **Step 7：更新状态并尝试提交。** 记录真实包哈希、文件数、SDK/Python 版本和门禁结果；
  说明尚未认证、取行情、验证策略或连接期货账户。保留 Git 作者信息缺失的实际状态，
  不把“导入成功”写成“可以实盘”。

## 自评与交接

方案的封存、完整恢复、上下文入口、环境隔离、凭证边界及六项验收均已对应上述任务。
五项 Review Focus 分别落在 Task 2 的源文件二次复验、Task 1 恶意包测试、
Task 1 恢复拒绝测试、Task 3 失败恢复测试与 Task 3 环境身份检查。
新代码均集中在 tools/ 与 tests/；除小型校验工具，不新增业务模块。

推荐当前会话由主代理直接按顺序执行，最后安排独立复核。
三个任务共享冻结清单且顺序紧密，这样可减少交接及上下文开销。
备选方式是每任务由新子代理实现并独立审阅，隔离更强、上下文与时间开销更大。
用户已确认并选择推荐方式，实施完成。

## 执行结果（2026-10-15）

- 98 个旧文件、625,594 字节完整封存；工作区外恢复与原冻结清单逐文件一致。
- 封存包 SHA256：c818c11e7ca184175ddc98f9a9cdf35ea00b4881a19a91be9cce7c31c8bdc088。
- Python 3.13.11、TqSdk 3.10.2 就绪；37 个安装发行版的依赖一致，官方 checker 返回 ready。
- tools/check.ps1 通过：21 个测试、Ruff、真实封存校验、环境身份、锁和依赖检查。
- 独立复核发现恢复时重新打开路径造成版本竞争；回归先复现，再改为同一份不可变字节，
  修复后全套通过。没有其他延期审阅项。
- 旧环境的 82 个受保护元数据文件及发行版集合未变；未认证、取行情、回测或交易。

实施裁定：在原 checkout 保全未提交成果；用 Windows 原生方式记录技能进度；
Git 作者信息缺失时不伪造身份，保留未提交状态和执行证据；
自动审批审核拒绝递归清理后，保留已忽略的旧缓存和空目录，不绕过重试。
代价分别为需要逐文件校验、保留本地进度、稍后配置 Git 作者，以及少量缓存磁盘占用。
