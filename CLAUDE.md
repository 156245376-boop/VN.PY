# 仓库地图

个人自用国内期货交易与回测系统。需求真相来源为
[`.kiro/specs/vnpy-futures-trading-system/requirements.md`](.kiro/specs/vnpy-futures-trading-system/requirements.md)(34 条 Requirement,EARS 格式)。
顶层设计与分阶段计划见 [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)。
**若你是被叫来审阅这套系统的模型,请先读 [`docs/REVIEW_ME.md`](docs/REVIEW_ME.md)。**

本文件的用途:把「跨 40 个文件 grep」变成「读一遍这份地图」。接口变更时必须在
同一个 commit 内更新此处(R26.8)。

## 环境

| 项 | 取值 | 为什么是这个值 |
|---|---|---|
| Python | **3.13.11**,`.python-version` 钉死 | vnpy_ctp 的 Windows wheel 只覆盖 3.10 与 3.13;3.13 是 vnpy 依赖 `PySide6==6.8.2.1` 允许的最高版本。详见 ADR-0014 |
| 虚拟环境 | `.venv/`,由 uv 创建 | 与系统 3.10 隔离 |
| 依赖 | 全部精确钉死于 `pyproject.toml` | CTP 版本与 Python 小版本绑定,放宽会失去升级时的对照基线。版本记录见 `docs/DEPENDENCIES.md` |
| 数据根 | `data/`(已 gitignore) | 运行期数据,布局见下 |

常用命令:

```powershell
.\tools\check.ps1                              # 全部确定性检查,推荐入口(R34.3)
.venv\Scripts\python.exe -m pytest tests/meta -q   # 单模块,秒级返回
.venv\Scripts\python.exe -m pytest -m "not pending_expected" -q   # 只跑已核对的部分
.venv\Scripts\python.exe tools\requirements_coverage.py --module meta  # AC 覆盖缺口(R34.12)
```

`check.ps1` 固定从仓库根执行并设置 `PYTHONUTF8=1`,依次运行 pytest、ruff、mypy、
import-linter 与 AC 覆盖标记校验。不要直接复制散落的子命令作为自动化入口。

**pytest 是两段式的,这一点容易踩坑**:`pytest` 单独运行**必然非零退出**,因为
`pending_expected` 用例被 R34.7 要求失败。门禁因此分两步 —— 已核对用例必须全过
(`-m "not pending_expected"`),待填用例必须不全过(它们若通过,说明 R34.7 的保护
已失效)。新增领域逻辑测试时,预期值未核对的那些必须打 `pending_expected`,不得
为了让 pytest 变绿而删掉标记。

## 分层规则(硬约束)

import 只能**向下**,不能横向进同级内部,不能向上。由 `.importlinter` 机械强制。

```
L9  apps/         CLI 入口、监控面板、录制器(唯一可 import runtime 的层)
L8  runtime/      实盘会话组装、状态持久化、调度、持仓对账
L7  engines/      gateway/        (同级不互相 import,由 runtime 汇合)
L6  execution/    risk/           (risk 不 import execution)
L5  costs/
L4  strategy/     indicators/     (strategy 可 import indicators)
L3  data/
L2  meta/
L1  config/       obs/
L0  core/
```

没有机械强制,「一次只改一个文件夹」会在两个月内失效。

## 模块清单

| 模块 | 层 | 职责 | 必须不知道 | 测试 |
|---|---|---|---|---|
| `core` | L0 | 共享值类型(Bar/Tick/OrderIntent/Fill)、枚举、异常分类、Clock 抽象 | vnpy、pandas、磁盘、网络、交易所规则、券商 | `tests/core` |
| `config` | L1 | 类型化配置加载与校验(R22) | 策略、委托、市场事实 | `tests/config` |
| `obs` | L1 | 日志、状态快照写入、告警推送(R20/R21) | 策略、委托、数据库 | `tests/obs` |
| `meta` | L2 | 合约表、交易日历与时段、费率保证金 SCD-2、代码规范化,及这些事实的 Reference_Data_Store 端口(R3/R27/R30) | 策略、委托、回测、vnpy、实盘状态 | `tests/meta` |
| `data` | L3 | 采集、存储、聚合、质量、主力连续(R4–R10/R28) | 策略、委托、风控、实盘。**`data/vnpy_db.py` 是本模块唯一可 import vnpy 的叶子文件** | `tests/data` |
| `indicators` | L4 | 纯 numpy 指标,标量式与序列式双形态(R33.7) | 策略、行情来源、磁盘 | `tests/indicators` |
| `strategy` | L4 | 策略纯逻辑(R11) | vnpy、交易所、平今平昨、费用、保证金、数据库、券商、委托号、网络 | `tests/strategy` |
| `costs` | L5 | 手续费、滑点、保证金(R29) | 引擎身份 —— 回测与实盘调用同一批函数 | `tests/costs` |
| `execution` | L6 | 目标持仓 → 委托、平今平昨决策、限价与涨跌停钳制(R17) | vnpy、网关、策略类、磁盘 | `tests/execution` |
| `risk` | L6 | 纯否决函数 `screen(intents, state, limits) -> Verdict`(R19) | 执行细节 | `tests/risk` |
| `engines` | L7 | vnpy 适配器(唯一同时知道 vnpy 与 Strategy 的地方)、回测装配(R12/R13) | — | `tests/engines` |
| `gateway` | L7 | CTP 连接、流控令牌桶、穿透式监管前置检查、每日费率快照(R1/R2) | 策略 | `tests/gateway` |
| `runtime` | L8 | 实盘装配、状态持久化、持仓对账、交易日调度、到期换月(R16/R18/R31) | — | `tests/runtime` |
| `apps` | L9 | CLI、监控面板、录制器 | — | `tests/apps` |

`apps/monitor.py` **只允许 import `obs` 与 `core`**(R24.14)。这条可机械检查,它保证
监控面板不可能意外拿锁、开 CTP 会话或碰交易库 —— 双进程方案(ADR-0008)的技术兑现。

## 标识的单一规范形式

同一个东西有多种写法,是这类系统最大的静默 bug 源。**每类标识只有一个规范形式,
转换只在最边缘发生。**

| 东西 | 规范形式 | 唯一转换点 |
|---|---|---|
| 合约 | `rb2510.SHFE`(品种按交易所大小写惯例、4 位年月、带交易所后缀) | `meta/symbols.py` 的 `to_canonical()` / `to_wire()` |
| 连续合约 | `rb.MAIN@oi_prev:back`(规则与复权方式编进标识) | 同上。**绝不可用于报单**(R28.10) |
| 时间 | tz-aware `Asia/Shanghai`,**Bar 时间戳 = 分钟起始** | 数据源适配器入口转换并断言(R10.6) |
| 交易日 | `date`,经 `to_trading_day()` 得出,夜盘已前滚 | `meta/calendar.py`,唯一出口(R3.4) |
| 方向/开平 | `core/enums.py` 自有枚举 | `engines/vnpy_bridge.py` 与 `gateway/` 转 vnpy 枚举 |
| 策略实例 | `(strategy_class, instance_name)`,重启后稳定 | 实例名进配置文件,不自动生成 |
| 委托 | `client_id`,格式 `{交易日}-{品种}-{序号}`,幂等键 | `runtime/state.py` 生成,只追加流水 |

这三类错误的共同特征是**不报错、结果还更好看**:`MA509` 到底是哪个合约、Bar 时间戳
差一分钟、连续合约代码误入报单。规范形式加边缘转换是唯一可靠的防法。

## 配置 vs 参考数据的分界

判据一句话:**「这个值在 2020 年有一个不同的正确答案吗?」**

- **有 → `meta/` 的带生效日期表**(SCD-2):费率、保证金率、交易时段、合约乘数、
  最小变动价位、交易日历、涨跌停幅度、合约挂牌与到期日期、结算价。
  放进 conf 里意味着回测 2019 年用的是今天的保证金(R22.1/R22.3)。
- **没有 → `conf/*.toml`**:数据根路径、日志级别、风控上限、订阅清单、tick 白名单、
  券商账号、策略参数。这些没有「历史正确值」,是你的决定。

## 状态所有权

每份状态**恰好一个所有者**,其他模块只读。两个模块都认为自己拥有持仓,就会发散。

| 状态 | 唯一真相 | 其他模块 |
|---|---|---|
| 实际持仓(含今/昨拆分) | **券商**(CTP 查询) | `runtime/state.py` 只是镜像;不符即冻结(R18.10) |
| 目标持仓 | 策略 | 执行层只读并负责收敛 |
| 委托生命周期 | 只追加的委托流水 `orders.jsonl` | 内存视图可重建(R17.16) |
| 账户权益/可用资金 | 券商 | 回测里由 `costs/` 计算 |
| 策略内部变量 | 策略自己,经 `get_state()` 导出 | `runtime/state.db` 只负责持久化,不解释内容 |
| 市场参考事实 | `meta/` 的 Reference_Data_Store | `data/` 与其他模块只经 `meta` 公开端口查询 |
| 告警记录 | `obs/` 的追加事件流 | Monitor_Shell 只读 |
| 已落库市场数据的存在性 | `data/` 的采集台账 + 来源表 | 不靠扫文件推断 |

## 进程边界与写锁

三个进程会同时活着。DuckDB 跨进程是单写多读、写时持排他锁 —— 不分清就会出现
**录制器拿不到锁而丢 tick**,而丢掉的历史数据买不回来。

| 进程 | 写什么 | 读什么 |
|---|---|---|
| 录制器 | `raw/**` Parquet(只追加、无锁)、`warehouse.duckdb` 的台账 | `meta/` |
| 构建任务 `qf data build` | `curated/**`、`warehouse.duckdb` | `raw/**` |
| 实盘进程 | `runtime/state.db`、`orders.jsonl`、`snapshot.json` | `curated/` 预热数据、`meta/` |
| 回测/研究 | 只写 `results/` | **`warehouse.duckdb` 必须以 read-only 打开**(R6.16) |
| 监控面板 | 什么都不写 | 只读 `snapshot.json` + `events.jsonl` |

两条硬规则:**录制器与构建任务不同时跑**(构建安排在收盘后,R6.17);**回测一律
read-only 连接**。

## 数据根布局

```
data/
├─ raw/          不可变。永不编辑、永不删除、只追加(R6.8/R25.12)
├─ curated/      派生。可由 raw 完全重建,删了无所谓(R6.7)
│                bar1m/product=rb/year=2024/  ← 分区选 product+year
├─ meta/         contracts / calendar / sessions / params / roll_map (SCD-2)
├─ warehouse.duckdb   台账、来源表、质量记录、视图 —— 只放小的可变表
├─ runtime/      snapshot.json  events.jsonl  state.db  orders.jsonl
└─ logs/trading_day=20250801/*.jsonl
```

**唯一不可重建的是 `raw/`** —— 代码能重写,`curated/` 能重建,自录 tick 没了就
永久没了。备份接口见 R25.13。

## CLI 命名空间

单一入口 `qf`,不使用其他命令名(计划第 9 节):

```
qf data ingest|build|cont|quality|gaps|show|params
qf bt   run|sweep|report
qf live run|status|flatten|recon|slippage
qf rec  start|status
```

## 开发约定

1. **单文件上限 400 行**(R24.11)。漂亮的目录树里躺一个 1500 行的 `data/store.py`,
   整个方案就白费了 —— 读一个文件是不可压缩的成本。
2. **公开面要窄**:`__init__.py` 只 re-export 少量公开名,其余下划线开头。
   改 `execution/` 的人读 `meta/__init__.py`,不读 `meta/` 的五个实现文件。
3. **每模块 README 的「公开接口」小节必须与 `__all__` 完全一致**,由
   `tests/test_docs_contract.py` 强制(R26.6)。说谎的文档比没有文档更糟。
4. **接口变更与 README/ADR 更新在同一个 commit 内**(R26.8)。
5. **跨模块边界用 `Protocol`**,让一侧能对着 20 行契约改而非对着实现改(R24.8)。
6. **领域逻辑测试的预期值必须来自系统外部权威资料**(R34.4–R34.7)。模型只写测试
   输入与结构,预期值标 `pending_expected` 并由开发者查阅交易所公告后填入 ——
   否则测试退化为「模型的理解 == 模型的实现」,证明力为零(ADR-0001)。
7. **禁止在 `core/timeutil.py` 之外调用系统时钟**(R33.2)。策略连 Clock 都不碰,
   时间由引擎经 Strategy_Context 供给(R11.6)。
8. **验收标准覆盖必须显式声明**:测试以 `pytest.mark.covers("R<n>.<m>")` 标记覆盖关系,
   `tools/requirements_coverage.py` 只认该标记,不从测试名或注释猜测(R34.12)。
9. **市场数据、参考事实、运行状态、告警各有所有者**:`data` / `meta` / `runtime` /
   `obs` 分别持有自己的存储端口,不得为方便把四类状态重新塞进一个 Data_Store。
10. **交易日判定只经 `TradingCalendar.to_trading_day()`**(R3.4)。任何 `dt.date()`
    或"工作日推算"都是绕过,且错了不会报错 —— 1 分钟 Bar 看起来完全正常。
11. **领域逻辑测试分两类文件**:结构与算法测试的预期值可由输入推得;市场事实
    (交易日历、交易所时段、代码惯例)必须放 `pending_expected`,由开发者查资料填入
    (R34.4–R34.7)。`pending_expected` 用例不得声明 `covers`,由覆盖工具强制。
