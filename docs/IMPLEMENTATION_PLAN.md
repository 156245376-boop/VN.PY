# 个人期货交易系统 — 顶层设计与实施计划

## Context

要做一套个人自用的国内期货交易系统：能对多品种、多合约做多年 1 分钟 K 线回测，能接免费实时行情做全自动实盘，且模块化到"改一个模块只进一个子文件夹"的程度。

项目目录 `d:\自研交易软件+系统`。需求真相来源为 `.kiro/specs/vnpy-futures-trading-system/requirements.md`（已按本计划修订定稿，736 行 EARS 格式，34 条 Requirement）。

这份需求文档质量高于多数个人项目，核心原则（自建数据资产为主、免费源仅回补、模块物理隔离、不自研图表看盘）与本次讨论一致。但逐条交叉检查后发现 **24 处逻辑问题**，其中 4 处经本地 vnpy 4.4.0 源码实测确认为**技术上做不到**，另有 1 处缺失会**直接产生资金损失**。本计划的主要产出是：修订清单 + 能落地的模块划分 + 分阶段实施顺序。

本机（RTX 4090 / i5-13600KF，14 核 20 线程）即开发机。计划初稿曾在另一台 MX250 上写就，本文件已按本机实测事实校正（见下）。

---

## 已定决策（本次讨论确认，不再重议）

| 决策 | 结论 | 理由 |
|---|---|---|
| 语言 | **Python** | CTP API 底层已是原生 C++（`vnpy_ctp` 是 pybind11 包装上期技术 SDK）。行情为 ~500ms 快照，1 分钟策略决策周期 60,000ms，语言层开销占 ~0.0005%。C++ 只在 tick 级回测（10⁹ 事件）有意义，而那里正确答案是 Polars/DuckDB/Numba 而非手写 C++ |
| 框架 | **vn.py 4.4.0 + vnpy_ctp** | 已装 vnpy 4.4.0 |
| 回测引擎 | 先用 `vnpy_ctastrategy`，**预留替换** | 靠适配器边界实现，见"策略可移植契约" |
| 策略基类 | **纯逻辑类 + 薄适配器**，不直接继承 `CtaTemplate` | 同时解决 R11.1⊗R13 冲突，且保住引擎可替换性 |
| 手续费 | **自建费用模块，回测实盘共用同一函数** | vnpy 回测只支持 `turnover×rate`，收不到按手固定费和平今差异 |
| 运行形态 | **双进程**：录制器 headless 常驻 + GUI 只做监控 | 夜盘无人值守；丢掉的历史数据买不回来 |
| 自动化程度 | **全自动，风控内自主下单** | 前提是先在模拟盘验证完整的断线重连与持仓对账 |
| 机器学习 | **预留接口，现在不做** | 免费 1 分钟历史短且有缺口，数据攒够前做 ML 等于拿噪音训练 |
| 多品种引擎 | **实测后再定**（见 Phase 5a） | 不拍脑袋选 |
| 账户 | 已有实盘账户，实时行情与实盘链路现在可测 | |

### GPU / 4090 的定位（结论：前 90% 的工作用不上）

回测是**路径依赖**的（第 2 分钟的持仓取决于第 1 分钟的决定），无法把时间轴切给几千个 GPU 核并行。参数扫描虽可并行，但每组参数的代码里全是分支判断（突破没？止损没？换月没？），而 GPU 是 32 线程一组必须同步执行同一指令，分支一多效率就崩（warp divergence）。

量级上：250 交易日 × 100 合约的 1 分钟 K 线 ≈ 860 万根，Numba 编译后约 2 秒；数据搬进显存再搬出就不止 2 秒。**这个量级用 GPU 是净亏。**

真正吃满的是 **CPU 多核**（参数扫描，按物理核心数配进程）、内存、SSD。4090 的用武之地只有两处：将来的 ML 模型训练、以及 tick 级大规模因子计算。所以 ML 只预留接口，不现在做。

---

## 本地环境实测事实（本机，2026-08-30）

```
Python        3.13.11（64 位 CPython，由 uv 安装至用户目录）
vnpy          4.4.0
vnpy_ctp      6.7.11.4      ← 实盘接口，已在 3.13 上验证 import 成功
vnpy_ctastrategy   1.4.1
vnpy_ctabacktester 1.3.0
numpy 2.5.2 / pandas 2.3.3 / TA-Lib 0.7.1 / PySide6 6.8.2.1
vnpy_portfoliostrategy 未装（Phase 5a 选型时再装）
```

`python` / `python3` 在 PATH 是 Microsoft Store 别名占位，不可用；实际解释器由 uv
管理（`.python-version` 钉死 3.13）。**解释器版本由 vnpy_ctp 的 wheel 矩阵反向决定：
其 Windows wheel 只覆盖 cp310 与 cp313，而 vnpy 钉死 `PySide6==6.8.2.1`（声明
`<3.14`），故 3.13 是同时满足两边的最高版本** —— 完整推导见 ADR-0014。

关键源码事实（决定了下面的修订清单）：

| 事实 | 位置 |
|---|---|
| `BacktestingEngine.set_parameters(vt_symbol: str, ...)` — **单合约引擎** | `vnpy_ctastrategy/backtesting.py:114` |
| 手续费只有 `self.commission += turnover * rate` — **无按手固定费、全局仅一个 rate** | `vnpy_ctastrategy/backtesting.py:1123` |
| 限价撮合用 `bar.low/high` 判定、`bar.open` 作最优价 → 实际成交价 = `min(委托价, 下根Bar开盘价)`，比 R12.2 写的更保守 | `vnpy_ctastrategy/backtesting.py:671` |
| `BarData` 字段无任何来源标识 | `vnpy/trader/object.py:88` |
| `BaseDatabase` 仅 8 个方法，全是 tick/bar | `vnpy/trader/database.py:52` |
| `PositionData` 有 `yd_volume`（昨仓） | `vnpy/trader/object.py:178` |
| `OffsetConverter.convert_order_request(req, lock, net)` 已实现平今/平昨拆分（靠 lock/net 布尔参数区分，非独立方法） | `vnpy/trader/converter.py:367` |
| `TargetPosTemplate` 已有目标持仓模式可参考 | `vnpy_ctastrategy/template.py:370` |
| `vnpy.alpha` 是 vnpy 4.x 内置模块（需 `vnpy[alpha]` extra 含 alphalens-reloaded/lightgbm/torch）：`set_parameters(vt_symbols: list[str])`、`AlphaStrategy.on_bars`、原生 `set_target/get_target`、polars | `vnpy/alpha/strategy/backtesting.py:70`、`template.py:129` |

`vnpy.alpha` 是唯一原生多合约 + 原生目标持仓 + GPU 可用的一套，但其内置因子集 Alpha158 源自微软 Qlib、示例是股票策略，**期货的保证金/平今/合约乘数大概率未处理**（源码结构推断，未实测）。故列入 Phase 5a 实测。注意：它依赖 `vnpy[alpha]` extra（alphalens-reloaded 等），当前未安装，Phase 5a 实测前需先补装。

---

## requirements.md 修订清单（24 项）

### A. 技术上做不到（已在源码验证，必须改）

| # | 冲突 | 改法 |
|---|---|---|
| A1 | **R11.1 强制继承 `CtaTemplate` ⊗ 引擎可替换**。直接继承会永久锁死 vnpy，将来换引擎要重写每个策略 | 改为：策略是纯逻辑类，只依赖 numpy 和自有类型；`CtaTemplate` 降为薄适配器（约 80 行，全项目唯一 import vnpy 的策略侧文件） |
| A2 | **R13 多品种组合回测 ⊗ R11.1**。`set_parameters` 只收一个 `vt_symbol` | 靠 A1 的适配器解决：单品种走 `CtaTemplate`，多品种走另一个适配器（引擎见 Phase 5a 实测） |
| A3 | **R12.4 按手固定费 ⊗ vnpy 回测只有 `turnover×rate`**；且全局仅一个 rate，导致 **R17.5 要求实盘区分平今平昨、但回测收不到不同费用** | `rate` 设 0，自建费用模块按「元/手 + 比例 + 平今差异」计算并从权益扣除，**回测与实盘调用同一函数**。需接管日结算计算 |
| A4 | **R9.6「保留自建通道记录」做不到** — `BarData` 无任何来源字段，而 R6.8 要求同键只留 1 条 | 建独立来源表：(合约, 交易所, 周期, 时间戳) → 来源 + 写入时间 + 校验和。这是「自建数据资产为主」这条核心原则能否落地的关键 |
| A5 | **R7.6 / R8.6 / R16.4 / R21.7 无接口可用** — `BaseDatabase` 仅 8 个方法全是 tick/bar，存不了质量报告、异常标记、策略变量、告警记录。若把四类状态都塞进 Data_Store，又会让 `data` 夺走 `runtime`/`obs` 的状态所有权 | 市场数据边界保留两组接口：vnpy `BaseDatabase`（供回测引擎读 Bar）+ 自有市场数据表（质量、来源、台账）。策略状态经 `runtime` 的 Runtime_State_Store 写 `state.db`；告警经 `obs` 写事件流；参考事实由 `meta` 的 Reference_Data_Store 持有 |
| A6 | **R23.1 GUI 为启动入口 + R23.6 关窗即停 ⊗ R5 全市场录制需 21:00–02:30 无人值守** | 双进程：录制器 headless 常驻，GUI 随时开关只做监控。改 R23.1/R23.6 |

### B. 会亏钱或静默出错

| # | 问题 | 改法 |
|---|---|---|
| B1 | **合约到期与交割全文零提及**。个人客户绝大多数商品期货不能进交割，必须在最后交易日前平仓，部分品种期货公司会提前强平。**全自动下系统某天会抱着仓位进交割月** | 新增需求：到期前 N 个交易日强制平仓/换月，N 按品种配置；临近到期禁止开新仓 |
| B2 | **Bar 时间戳是分钟开始还是结束，全文未定义**。vnpy 内部用**开始**时间，外部源各家约定不同 | 钉死为分钟开始时间；导入适配器（R10.4）做转换并加断言。**混用会整体错位一分钟，等于回测偷看未来，且结果只会变好看** |
| B3 | **R18.6「以 CTP 返回值为准自动更新本地持仓」**。最危险场景是「报单已发、回报未收」时断线：本地空仓、券商多 2 手 | 改为**冻结新开仓 + 推手机 + 人工确认后放行**，永不自动纠正。配合 client_id 幂等键 + 只追加的委托流水 |
| B4 | **R22.1 把手续费/保证金当静态配置项**。保证金变动频繁（节假日调高、波动率响应、交易所干预）。用今天的保证金回测 2019–2024，每个资金受限的结果都是错的 | 改为带生效日期的版本化表（SCD-2）。最佳免费来源是**自己账户的 CTP 查询**，返回的是含券商加成的真实费率 |
| B5 | **R12.9 确定性 ⊗ R9 回补**。R11.7 预热从库读 Bar，库内容因回补不断变化，同一条回测命令前后结果不同。前复权连续合约有同样毛病（每次换月重写全部历史） | 回测报告带**数据版本号/快照标识**，使每个结果可追溯 |
| B6 | **保证金上调未处理**。节假日前交易所调保证金，持仓过夜可能触发追保强平；R19 只在下单前检查 | 增加持仓期保证金监控 + 节假日前主动降仓策略 |
| B7 | **R8.1 只把涨跌停幅度当异常检测阈值**，未定义封板时的成交假设 | 回测中封板假设**完全不成交**。否则会恰好在最大单边行情那几根 K 线上凭空造出利润 |

### C. 缺失且必需

| # | 缺什么 | 为什么要紧 |
|---|---|---|
| C1 | **主力连续合约拼接与换月复权** | 单个合约只活 6–12 个月，不拼接就无法做多年回测 —— 这是 R12/R13 的前提。前复权/后复权/比例复权各有偏差，必须显式选，且换月要计费 |
| C2 | **结算价** | 每日盯市、保证金、单日亏损上限用的是**结算价**（加权均价）不是收盘价。R14 用收盘价会让 **R19.6 的亏损熔断在错误时点触发** |
| C3 | **穿透式监管 AppID/AuthCode/采集库** | 没有会登录失败，CTP 错误码不直观，通常 20:59 才发现。需做启动前置检查 |
| C4 | **郑商所 3 位/4 位年月码** | `MA509` 是 2015 还是 2025？导入历史数据时必炸。需带参考日期解析，歧义时报错不猜 |
| C5 | **CTP 查询流控（约 1 次/秒）** | R18.2 每 5 秒轮询资金持仓 + 登录时 `ReqQryInstrument`（几千条）会撞流控。R19 只管了下单和撤单频率，漏了查询 |

### D. 会被噪音淹没 / 状态发散

| # | 问题 | 改法 |
|---|---|---|
| D1 | **R5.8 ⊗ R7.1**：无成交不生成 Bar，但缺失检测按「应有分钟数」比对。冷门与远月合约大量分钟无成交 → **全市场录制下每天几千条假缺失告警**，R20.8 行情中断（60 秒无 tick）同理 | 缺失判定按流动性分级；冷门合约用「同期同品种主力有成交而本合约无」作为真实缺失的判据 |
| D2 | **R19.6 拒单 ⊗ 全自动**：策略以为开了仓、实际被风控拒了，内部状态与真实持仓发散，下根 K 线继续重试。**R17.8 部分成交后撤单**（要 3 手成交 1 手）是同一类问题 | 拒单和部分成交**必须回灌给策略**；策略以目标持仓表达意图，由执行层负责收敛 |
| D3 | **R19.9 计数重置时点含混**。「新交易日第一个交易时段开始」：有夜盘品种是前一自然日 21:00，无夜盘是 09:00。但单日亏损上限是**账户级**，不能由品种级事件触发 | 定义统一的账户级交易日切换时点 |
| D4 | **R4.6 无上界重试**：写库持续失败（磁盘满、锁表）时内存缓冲无限增长 → OOM → 全部丢失。且 **R25.2「当日写入失败条数为 0」是愿望不是可验证需求**，与 R4.6 承认会失败自相矛盾 | 重试设上限 + 落地文件兜底；R25.2 改为「失败记录必须落地且可重放」 |
| D5 | **R24.5 全市场 tick 走单一 EventEngine**：R1.7 每条 tick 一个事件，全市场订阅是每秒几千事件挤一条 Python 队列，还要和界面消费者抢（这正是 vnpy 事件引擎 20–30ms 延迟的成因） | 录制器**直连网关回调**，不挤 GUI 事件总线。双进程方案已经解决了大半 |
| D6 | **R22.4 环境变量优先 ⊗ R22.9 序列化往返**：有效配置来自环境变量时，序列化再解析无法还原 | 往返属性只对文件层配置成立，需限定范围 |

### E. 值得重估

- **R24.5「子系统间运行期数据传递通过 EventEngine 完成」过度了。** 日历判断、配置读取、数据库查询本质是函数调用，强行走事件会让测试和排查变难。更关键的是**事件名字符串是隐式耦合，依赖检查脚本（R24.7）看不见它**，反而削弱你要的「改一个模块」。建议：行情/委托/成交/持仓这类**异步推送**走事件，查询类走显式函数调用。
- **R25.4 默认 20 个 tick 合约的容量。** 20 × 约 4.1 万 tick/日 × 250 日 ≈ **每年 2 亿条**，按 vnpy tick 表字段估一年 30–50GB，**R25.7 那个 50GB 告警阈值一年内就会撞上**（这个数字本身说明写文档时已有预感）。建议 tick 走 Parquet 按交易日分区（列式压缩到 10–15 字节/行），SQLite/DuckDB 只放 Bar 和账本类小表。
- **R12.2「委托成交价取委托价格」与实际不符** —— 实测是 `min(委托价, 下根Bar开盘价)`，比文档写的更保守（这是好事，但文档要改准）。

---

## 模块划分

### 分层规则（硬约束）

import 只能**向下**，不能横向进同级内部，不能向上。

```
L9  apps/         CLI 入口、监控面板、录制器（唯一可 import runtime 的层）
L8  runtime/      实盘会话组装、状态持久化、调度、持仓对账
L7  engines/      gateway/        （同级不互相 import，由 runtime 汇合）
L6  execution/    risk/           （risk 不 import execution）
L5  costs/
L4  strategy/     indicators/     （strategy 可 import indicators）
L3  data/
L2  meta/
L1  config/       obs/
L0  core/
```

用 `import-linter` 机械强制分层（对应 R24.10），并由版本库内的 `tools/check.ps1` 统一设置 UTF-8 后执行 pytest、ruff、mypy 与 import-linter。CI 或提交钩子若后续引入，只调用这个单一入口，不复制命令。这不是装饰：没有它，「一次只改一个文件夹」会在两个月内失效，省 token 的前提也就没了。

### 目录树

```
d:\自研交易软件+系统\
├─ CLAUDE.md                  # 仓库地图：每模块一行职责 + 公开接口 + 允许的依赖
├─ pyproject.toml
├─ .importlinter              # 分层契约
├─ conf/
│   ├─ default.toml           # 路径、数据根、日志级别
│   ├─ local.toml             # gitignore：CTP 账号密码 AppID AuthCode（对应 R22.2）
│   └─ strategies/*.toml
├─ src/
│  ├─ core/          # L0 共享词汇：Bar/Tick/Fill/OrderIntent、枚举、异常、时区工具
│  ├─ config/        # L1 类型化配置加载与校验（R22）
│  ├─ obs/           # L1 日志 + 状态快照 + 告警推送（R20/R21，三者合一）
│  ├─ meta/          # L2 合约表、交易日历与时段、费率保证金 SCD-2、代码规范化（R3/R22.1）
│  ├─ data/          # L3 数据源、存储、聚合、质量、主力连续（R4–R10）
│  ├─ indicators/    # L4 纯 numpy 指标，标量式与序列式双形态
│  ├─ strategy/      # L4 策略纯逻辑（不 import vnpy）（R11）
│  ├─ costs/         # L5 手续费、滑点、保证金（A3 的落点）
│  ├─ execution/     # L6 目标持仓→委托、平今平昨、限价与涨跌停（R17.5）
│  ├─ risk/          # L6 纯否决函数（R19）
│  ├─ engines/       # L7 vnpy 适配器 + 回测配置 + 将来的自研引擎（R12/R13）
│  ├─ gateway/       # L7 CTP 连接、流控、穿透式监管、费率查询快照（R1/R2）
│  ├─ runtime/       # L8 实盘装配、状态、对账、调度、到期换月（R16/R18/B1）
│  └─ apps/          # L9 CLI、监控面板、录制器
├─ docs/
│   ├─ REVIEW_ME.md           # 给未来审阅者的入口与阅读顺序
│   └─ adr/                   # 架构决策记录，只追加不修改
│       ├─ INDEX.md
│       └─ 0001-*.md ...
├─ tests/                     # 与 src/ 1:1 对应
├─ research/                  # notebook，可 import 任何东西，无人 import 它
└─ data/                      # 运行期数据根（gitignore），布局见下节
```

### 各模块职责与"必须不知道什么"

| 模块 | 职责 | 必须不知道 |
|---|---|---|
| `core` | 共享值类型、枚举、时区工具 | vnpy、pandas、磁盘、网络、交易所规则、券商 |
| `obs` | 日志 / 状态快照写入 / 告警推送 | 策略、委托、数据库 |
| `meta` | 合约、日历、时段、费率保证金（带生效日期）、代码规范化 | 策略、委托、回测、vnpy、实盘状态 |
| `data` | 采集、存储、聚合、质量、主力连续 | 策略、委托、风控、实盘。**`data/vnpy_db.py` 是本模块唯一可 import vnpy 的叶子文件** |
| `strategy` | 纯策略逻辑 | vnpy、交易所、平今平昨、费用、保证金、数据库、券商、委托号、网络 |
| `execution` | 目标持仓 → 委托，平今平昨决策，限价与涨跌停钳制 | vnpy、网关、策略类、磁盘 |
| `risk` | 纯否决函数 `screen(intents, state, limits) -> Verdict` | 执行细节 |
| `engines` | vnpy 适配器（唯一同时知道 vnpy 和 Strategy 的地方）、回测装配 | — |
| `gateway` | CTP 连接、流控令牌桶、穿透式监管前置检查、每日费率快照 | 策略 |
| `runtime` | 实盘装配、状态持久化、持仓对账、交易日调度、到期换月 | — |

`apps/monitor.py` **只允许 import `obs` 和 `core`**。这条可机械检查，它保证监控面板不可能意外拿锁、开 CTP 会话或碰交易库 —— 这正是双进程方案的技术兑现。

### 建议合并、不要拆的

| 想拆的 | 结论 | 理由 |
|---|---|---|
| 日志 / 告警 / 监控 分三个包 | 合成 `obs/` | 各不到 200 行，总是一起改，共用同一套事件词汇 |
| 日历 / 合约 / 费率 / 代码规范化 分四个包 | 合成 `meta/` | 同一套「某日期下的市场参考事实」，同一套 SCD-2 版本机制，使用方一次常需两三个 |
| 采集 / 存储 / 质量 分三个包 | 合成 `data/` | 采集离开存储的幂等台账没有意义，质量要同时读两边 |
| 回测引擎 / 实盘引擎 分开 | 一个 `engines/` | vnpy 回测与实盘用**同一个** `CtaTemplate`，一个适配器同时服务两边。拆开会招致分裂，而**分裂是回测实盘不一致的头号来源** |
| `portfolio/` 组合分配 | 暂不 | 等真有多策略再说 |
| 主力连续单独顶层 | 放 `data/continuous/` 子文件夹 | 它是派生数据构造；顶层会诱发 data↔continuous 循环。放子文件夹将来提取只是一次 `git mv` |
| 再造一套事件总线 | 不要 | vnpy 已有 `EventEngine` |

### 「一个模块一个子文件夹」到底能不能省 token —— 老实说：能，但只占 20–30%

AI 花 token 的地方按量排序是：①搜索定位 ②读文件重建隐式契约 ③读真正要改的那个文件。**文件夹结构只帮到 ①，而且仅当命名可预测时。**

要真省下来，还必须同时做到：

1. **根目录 `CLAUDE.md` 仓库地图**（约 150 行）：每模块一行职责、公开接口名、允许的依赖、测试在哪。**这是整个项目里性价比最高的一份文件** —— 它把「跨 40 个文件 grep」变成「读 150 行」。Phase 0 就写，接口变更时同一个 commit 里更新。
2. **每模块 `README.md`（10–25 行）**：职责、公开接口、不变式、禁止 import 清单、测试命令。这才是「只改一个模块」真正的实现机制。
3. **公开面要窄**：`__init__.py` 只 re-export 少量公开名，其余下划线开头。改 `execution/` 的人读 `meta/__init__.py`（30 行），不读 `meta/` 的五个实现文件。
4. **无循环依赖，机械强制**。有循环时「一次改一个模块」是幻觉。
5. **跨模块边界用 `Protocol`**：让一侧能对着 20 行契约改，而不是对着另一侧的实现改。
6. **单文件上限约 400 行**。漂亮的目录树里躺一个 1500 行的 `data/store.py`，整个方案就白费了 —— 读一个文件是不可压缩的成本。
7. **每模块的测试能在几秒内跑完**（`pytest tests/meta -q`）。验证成本也是 token 成本：如果改个日历要跑全量测试或连 CTP 才能验证，那段 transcript 你也得付钱。
8. **抵制过度拆分**。25 个微包时，一次现实的改动会碰到五个包，AI 得先读五份 README 加五个 `__init__.py` 才动手。**granularity 的检验标准：一次坐下来能做完的改动，应该只碰 1–2 个文件夹。** 上面 14 个模块是照这个标准定的。

所以：文件夹照拆，但要明白**真正付钱的是仓库地图、强制的无环分层、和文件大小纪律**。文件夹是档案柜，地图和接口纪律才是索引。

---

## 文档体系：让未来的审阅者看懂设计意图

目标是几十个版本迭代之后，把这个仓库交给一个更强的模型（或者过了半年的你自己），它能**快速看懂设计意图，并且知道哪些地方可以讨论改进**。

**先说一个反直觉的点**：写"本模块负责聚合 K 线"这类文档，价值很低 —— 模型读代码就能推出来，而且推得比文档准。模型**无法从代码里恢复**的是：

- 为什么选了这个方案
- 否决过哪些方案，为什么否决
- 哪些约束是承重的，哪些只是当时figured顺手
- 什么试过了、失败了
- 哪些不变式绝对不能破

所以文档的重点不是"是什么"，而是**"为什么"和"否决过什么"**。三层结构，各管一件事，互不重复。

### 第一层：`docs/REVIEW_ME.md` —— 给审阅者的入口（约 30 行）

直接为你这个需求服务的文件。内容是一份**阅读顺序**，而不是内容本身：

```markdown
# 如果你是被叫来审阅这套系统的模型，请按这个顺序读

1. 本文件（你在这）
2. CLAUDE.md —— 仓库地图，14 个模块各是什么、依赖方向
3. docs/adr/INDEX.md —— 所有架构决策，标了哪些是承重的
4. src/strategy/README.md + src/engines/README.md
   ↑ 整个系统最关键的边界。若要提改进意见，先理解这里
5. docs/adr/0003-*.md（目标持仓而非委托）、0005-*.md（费用回测实盘共用）
   ↑ 两个承重决策，动它们会连锁

## 本系统的核心约束（不理解这些，任何建议都会跑偏）
- 行情是 ~500ms 快照，不是逐笔。策略跑 1 分钟周期
- 回测与实盘必须调用同一个费用函数（历史原因见 ADR-0005）
- 免费 1 分钟历史短且有洞，自建录制是主要数据来源
- 单人维护。可维护性优先于性能，除非有 profile 数据

## 我们知道的、还没解决的问题
（链到 ADR 里标记为"已知局限"的条目）
```

**为什么值得单独一个文件**：它把"到处翻"变成"照单读"，既省 token 又让审阅者不会一上来就提一个我们两年前已经否决过的方案。

### 第二层：每模块 `README.md` —— 固定模板（15–30 行）

**模板必须固定**，因为固定的小节顺序 = 可预测 = 模型知道去哪一段找，不用通读：

```markdown
# <模块名>   （层级：L3）

## 职责
一句话。

## 公开接口
（必须与 __init__.py 的 __all__ 完全一致，有测试强制，见下）

## 不变式
必须永远成立的事实，以及破坏后会发生什么。
例：所有交易日判定只经 to_trading_day()。绕过它会导致日线聚合、
    单日亏损限额、结算 PnL 静默出错，而 1 分钟 Bar 看起来正常。

## 禁止 import
本模块不允许知道什么，以及为什么。
例：不得 import vnpy —— 否则策略被锁死在 vnpy，引擎不可替换（ADR-0002）

## 为什么这么设计
承重决策，链到 ADR。

## 否决过的方案            ← 给未来审阅者最关键的一节
例：曾考虑直接用 vnpy 的 ArrayManager。否决原因：它在 vnpy.trader.utility，
    会把 vnpy 拖进 strategy 的 import 闭包。另外它每根 K 线做一次
    array[:-1] = array[1:] 整体搬移，我们的环形缓冲是摊还 O(1)。

## 已知局限
当前实现的妥协，以及在什么条件下应该重做。
例：预热按根数、vnpy load_bar 按自然日，跨节假日有偏差。
    现用 series.inited 兜底。若将来自研引擎接管预热，这条可以消掉。

## 测试
pytest tests/<module> -q
```

**「否决过的方案」和「已知局限」这两节是整套文档的价值所在。** 前者防止审阅者重提旧议，后者主动告诉审阅者"这里我们自己也不满意"—— 这正是你说的"有更好的逻辑就能讨论"最容易发生的地方。

### 第三层：`docs/adr/` —— 决策记录，只追加不修改

编号、按时间排列、**永不编辑历史**（要改就写新的一条标记取代旧的）。这样才能看到设计是怎么演化的，而不只是当前快照。

```markdown
# ADR-0003：策略表达目标持仓，而非委托

状态: 生效
日期: 2026-08-02
承重性: **承重** —— 改动会波及 strategy/、execution/、engines/ 全部适配器

## 背景
当时的约束：需要同一份策略跑 vnpy 单品种回测、多品种回测、实盘，
且保留将来换自研引擎的可能。

## 决策
策略只调 set_target(symbol, volume)，不直接下单。

## 理由
若策略说"用 CLOSE_TODAY 买 2 手"，它就必须知道上期所规则、自己的
今昨仓拆分、涨跌停价、平今费差 —— 任何自研引擎都无法复现。
说"我要净持 −2 手"则三种引擎都能各自实现。
附带收益：拒单和部分成交不需要策略纠正状态（目标没变，执行层继续收敛）。

## 放弃的方案
- 策略直接继承 CtaTemplate 下单：最省事，但永久锁死 vnpy，
  且 set_parameters 只收单合约，多品种做不了。
- 策略产出信号强度让外层翻译：多一层间接，且信号→仓位的映射
  本身就是策略的一部分，拆出去反而更难理解。

## 后果
好：三引擎可移植、状态发散问题消失。
坏：挂单和停止单要走 place() 逃逸口，且失去向量化能力（标 vectorizable=False）。
```

**`承重性` 这个字段是关键。** 它直接回答你说的"有更好的逻辑能讨论"：审阅者一看就知道哪些决策动了会连锁、哪些是可以随便换的局部选择。没有这个标记，审阅者要么不敢动，要么动了不知道代价。

`docs/adr/INDEX.md` 一行一条，标状态和承重性，供快速扫。

### 让文档不说谎的机械手段

**说谎的文档比没有文档更糟** —— 未来的模型会信它。所以：

1. **公开接口列表可机械校验**：一条测试断言每个 `README.md` 的「公开接口」小节列出的名字与该模块 `__init__.py` 的 `__all__` 完全一致，不一致就 fail。这条便宜且有效，至少保证 README 在接口这件事上不撒谎。
2. **ADR 引用不能悬空**：脚本检查所有 `ADR-00XX` 引用都存在，且被标记「已取代」的 ADR 不再被生效文档引用。
3. **同一个 commit 内更新**：接口变更与 README/ADR 更新必须在同一个 commit。写进 `CLAUDE.md` 的开发约定。
4. **只写"为什么"，不写"是什么"**：不复述代码能表达的东西。README 里不出现函数签名的逐条说明 —— 那是代码和类型标注的工作，抄一遍只会腐烂。

### 与需求文档的关系

`requirements.md` 是**真相来源**（要什么），ADR 是**决策记录**（为什么这么实现），README 是**局部契约**（这个文件夹的规矩）。三者不重复：需求说"系统应区分平今平昨"，ADR 说"为什么费用计算放在 costs/ 而不是引擎里"，README 说"execution/ 不得 import vnpy"。

**Phase 0 就建立这套骨架**（模板 + 空 ADR 目录 + REVIEW_ME.md + 那条接口一致性测试），之后每个 Phase 结束时补齐当阶段的 ADR。事后补是补不出来的 —— 决策当时的约束和否决理由，过两周就想不起来了。

---

## 策略可移植契约（整个方案最关键的一处，A1/A2/D2 都靠它）

### 承重决策：策略表达的是「目标持仓」，不是「委托」

如果策略说"用 `CLOSE_TODAY` 买 2 手"，它就必须知道上期所、自己的今仓昨仓拆分、涨跌停价、平今与平昨的费差 —— 任何自研引擎都无法复现这套行为。

如果策略说"我要在 `rb2510` 上净持 −2 手"，那么：

- 实盘：与券商真实持仓做差，由 `execution/` 解析开平方向（可复用 `vnpy/trader/converter.py:367` 的 `convert_order_request(req, lock, net)`，靠 lock/net 布尔参数拆平今平昨）
- vnpy 回测：同样做差，通过 `buy/sell/short/cover` 表达
- 自研引擎：直接物化成目标持仓数组，用 `diff(target) × 价格` 减建模成本算 PnL

这同时解决了 **D2**：拒单和部分成交不再需要策略自己纠正状态 —— 目标没变，执行层下根 K 线继续收敛即可。

### 契约

```python
# strategy/context.py —— Protocol，使 strategy/ 对任何引擎零运行期依赖
class StrategyContext(Protocol):
    @property
    def now(self) -> datetime: ...          # 引擎供给；策略禁止调 datetime.now()
    @property
    def trading_day(self) -> date: ...      # 已按夜盘规则前滚

    def series(self, symbol: str) -> "SeriesView": ...
    def position(self, symbol: str) -> float: ...   # 仅供诊断，见"泄漏"第 2 条
    def target(self, symbol: str) -> float: ...
    def set_target(self, symbol: str, volume: float,
                   ref_price: float | None = None) -> None: ...   # 主要动作

    def place(self, intent: OrderIntent) -> str: ...  # 逃逸口，放弃向量化
    def cancel(self, client_id: str) -> None: ...
    def log(self, msg: str, /, **kv) -> None: ...
    def param(self, name: str) -> Any: ...

# strategy/base.py
class Strategy(ABC):
    symbols: tuple[str, ...]
    warmup_bars: int = 0        # 引擎保证 on_bar 首次触发前已有这么多根
    vectorizable: bool = True   # 用了 place() 就置 False

    def on_start(self) -> None: ...
    def on_stop(self) -> None: ...
    def on_trading_day_start(self, day: date) -> None: ...   # 结算/换月钩子

    @abstractmethod
    def on_bar(self, bars: Mapping[str, Bar]) -> None:
        """每个收盘的 K 线周期调用一次，含所有出了 Bar 的已订阅合约。
        bars 及其中的 Bar 是临时对象，禁止保留引用。"""

    def on_fill(self, fill: Fill) -> None: ...
    def get_state(self) -> dict: return {}      # 盘中重启恢复用，须 JSON 可序列化
    def set_state(self, state: dict) -> None: ...
```

`on_bar` 从第一天就收 **Mapping**。多合约不是后期功能 —— 用单个 `bar` 参数起步，将来retrofit 要重写每个策略和两个适配器。

### 状态：自己写环形缓冲，不用 vnpy 的 `ArrayManager`

`ArrayManager` 的**模式**是对的（定长 numpy 数组 + `inited` 标志 + ndarray 属性），但**类**不能依赖 —— 它在 `vnpy.trader.utility`，会把 vnpy 拖进 `strategy/` 的 import 闭包，那正是这一整节要防的事。自己实现约 60 行，且用 2 倍后备存储 + 回绕时 rebase，取代 `ArrayManager` 每根 K 线 `array[:-1] = array[1:]` 的整体搬移：push 摊还 O(1)，读取零拷贝且连续。

指标是这些视图上的**自由函数**（`sma_last(ctx.series(sym).close, 20)`），不是缓冲区的方法 —— 这样 `indicators/` 能被自研引擎和 research notebook 复用。

每个指标都提供**双形态**，并用参数化测试断言二者在随机输入下一致：

```python
def sma_last(x: np.ndarray, n: int) -> float: ...        # 标量，最新值
def sma_series(x: np.ndarray, n: int) -> np.ndarray: ... # 全历史，NaN 填充
```

这条不变式是将来向量化引擎的门票。

### 适配器：一个文件同时服务 vnpy 回测和 vnpy 实盘

`vnpy_ctastrategy` 的回测与实盘用的是**同一个** `CtaTemplate`，所以只有一个桥，不是两个：

```python
# engines/vnpy_bridge.py —— 全项目唯一同时知道 vnpy 和 Strategy 的文件
class VnpyBridge(CtaTemplate, StrategyContext):
    def on_bar(self, bar):                      # vnpy BarData
        b = to_core_bar(bar)                    # 经 meta.calendar 补 trading_day
        if b.trading_day != self._td:
            self._td = b.trading_day
            self._strat.on_trading_day_start(b.trading_day)
        self._now = b.dt + timedelta(minutes=1) # Bar 收盘时刻，避免未来函数
        self._series[b.symbol].push(b)
        if self._series[b.symbol].inited:
            self._strat.on_bar({b.symbol: b})
        self._sync_targets(b)
        self.put_event()

    def set_target(self, symbol, volume, ref_price=None):
        self._targets[symbol] = float(volume)

    def _sync_targets(self, bar):
        self.cancel_all()                        # Bar 收盘模型：不留挂单
        delta = self._targets[bar.symbol] - self.pos
        if not delta: return
        px = pricing.limit_price(bar, delta, self._ref_price)   # execution/pricing.py
        for offset, vol in offsets.resolve(...):                # execution/offsets.py
            ...
```

两点必须说清：

- **实盘**：vnpy 的 `OffsetConverter` 能替你拆平今平昨，但**决策**（今天这个品种哪条腿更便宜）属于 `execution/offsets.py`。桥先问 `execution/`，再用 vnpy 的词汇表达答案。
- **回测**：`BacktestingEngine` 完全没有今仓昨仓概念，所以开平解析在那边是空操作，**经济差异全部由 `costs/fees.py` 承担** —— 它拿到的是已解析的 offset。两条路径调**同一个费用函数**，这个同一性正是防止回测与实盘分裂的机制（A3）。

### 老实说什么会泄漏

**不泄漏**（可用 grep + import-linter 验证）：交易所身份、平今平昨、费率、保证金、委托号、券商、数据库、时区转换、夜盘交易日映射、合约乘数、换月日期。

**按设计泄漏，必须写进 `strategy/README.md`**：

1. **Bar 对象是临时的。** 自研引擎复用同一个可变对象。策略把 `bars["rb"]` 存进 list 就会拿到脏数据。用 `--strict` 调试模式发放冻结副本，并断言两种模式结果一致。
2. **`position()` 语义差一根 K 线。** vnpy 回测里下根 K 线的合成成交才更新 `self.pos`；实盘是真实 `on_trade` 异步且可能部分成交。**所以策略决策必须依据 `target()`，`position()` 只作诊断。这是回测实盘不一致的头号来源**，要在 README 里加粗。
3. **`place()` / 挂单 / 停止单不可向量化。** 用了就标 `vectorizable = False`，向量引擎直接报错而非静默错算。
4. **盘中事件。** 1 分钟 OHLC 无法确定盘中触发的止损。这个假设由 `engines/fill.py` 显式持有（悲观：先假设走到不利极值），而不是让每个引擎自己发明一套。
5. **预热边界。** vnpy 的 `load_bar(days=N)` 按自然日，而 `warmup_bars` 按根数。桥用 `meta.calendar` 换算，跨节假日必然有偏差 —— 所以判据是 `series.inited`，不是数根数。

**边界的验收测试（Phase 8 门槛）**：同一个策略文件、同一份数据，分别过 vnpy 回测和自研引擎，成交清单与 PnL 必须在浮点误差内一致。不一致就说明边界漏了，而这件事应该由测试告诉你，不是由亏钱告诉你。

---

## 数据层

### 结论：Parquet 落盘为准，DuckDB 作查询引擎；不用 MySQL

- **SQLite/MySQL 走 vnpy `BaseDatabase`**：一根 Bar 一行 + (symbol, exchange, interval, datetime) 索引。约 60 品种 × 各约 10 合约 × 多年 1 分钟，轻易到 2–5 亿行，文件 30–80GB，且高重复列毫无压缩。少量合约够用，做地基不行。
- **DuckDB 原生文件当存储**：查询引擎优秀，但单文件不便选择性同步，且跨版本文件格式变动是真实麻烦，还失去把单个分区直接交给 pandas/Polars 的能力。
- **Parquet + DuckDB 查询层**：追加为主、列式、ZSTD 下 1 分钟 Bar 约 10–15 字节/行，分区裁剪免费，DuckDB 读 hive 分区带谓词下推，任何单文件都能被 Polars/pandas/Arrow 独立读取。重建一个分区是目录级操作。**单机单人读多写少，这是正确默认值。**

DuckDB 仍保留一个持久文件，但只放**小的可变表**：采集台账、质量台账、**来源表（A4）**、换月映射、以及覆盖 Parquet 树的视图。大的不可变数据进 Parquet，小的账本类进 DuckDB。

### 布局

```
data/
├─ raw/                                   # 不可变。永不编辑、永不删除、只追加
│  ├─ ctp_tick/trading_day=20250801/rb2510.parquet
│  ├─ ctp_query/trading_day=20250801/{commission,margin,instrument}.parquet
│  ├─ exchange/exchange=SHFE/trading_day=20250801/dailydata.dat   # 原始字节
│  ├─ akshare/source=.../ingest_ts=.../payload.parquet
│  └─ tqsdk/symbol=SHFE.rb2510/ingest_ts=.../payload.parquet
├─ curated/                               # 派生。可由 raw 完全重建，删了无所谓
│  ├─ bar1m/product=rb/year=2024/part-000.parquet
│  ├─ bar1d/product=rb/part-000.parquet
│  └─ cont/rule=oi_prev/adj=back/product=rb/part-000.parquet
├─ meta/  contracts / calendar / sessions / params / roll_map / roll_events .parquet
├─ warehouse.duckdb                       # 台账、来源表、质量记录、视图
├─ runtime/  snapshot.json  events.jsonl  state.db  orders.jsonl
└─ logs/trading_day=20250801/*.jsonl
```

**分区选 `product=` 再 `year=`。** 不按合约分（几千个到期合约 → 几千个小文件，Parquet 元数据开销占主导）；不按交易日分（每品种每年 250 个文件 → 10⁵ 量级）。`product/year` 约 60 品种 × 10 年 = 600 个文件，几 MB 到几百 MB，正好在 Parquet 的甜点区。文件内按 **(symbol, dt) 排序**、ZSTD 3 级、row group 约 10–20 万行、写列统计，这样 `WHERE symbol='rb2510' AND dt BETWEEN ...` 能裁掉 row group —— **不用按合约分区也能获得合约级选择性**。

### raw 与 curated 的分界，以及幂等

规则：**raw 是数据源给你的原样（尽可能逐字节）；curated 是你对它的解释。** 清洗、时段映射、交易日归属、郑商所代码推断里的每个 bug，都靠从 raw 重建 curated 来修。**在采集时就清洗，这些 bug 会变成永久且不可发现的。**

- **raw**：键为 `(source, symbol_or_scope, trading_day)`。写 `*.tmp` → `os.replace`（NTFS 上原子）→ 插一条台账 `(键, 路径, 行数, sha256, 采集时间, 源版本)`。重复采集同键是空操作，除非 `--force` —— 那会用新的 `ingest_ts` 写**新文件**并把旧记录标为被取代，而不是覆盖。**观测记录永不丢失。**
- **curated**：永不追加，**整分区重写**。`qf data build bar1m --product rb --year 2024` 从 raw 重算该分区并原子换目录。Parquet 的"追加"是假的（意思是加文件，会破坏排序且重试时产生重复），整分区重写是唯一干净的幂等方案。推论：分区要小到重写便宜 —— `product/year` 正好合适。
- 台账同时回答"我到底有哪些数据"，这个问题你会反复问。
- **来源表（A4 的落点）**：`(symbol, exchange, interval, dt) → source, written_at`。回补时先查此表，自建通道的记录不被外部源覆盖。这是「自建数据资产为主」能否落地的技术前提。

### 免费数据源，按可信度排序

1. **自建录制（Phase 2 就开始，优先于一切）** —— 唯一你控制的源，也是唯一会**随时间变好**的源。level-1 约 2 快照/秒给你真实 tick、真实成交量持仓量，以及按你自己时段规则合成的 1 分钟序列。代价是必须 09:00–15:00 与 21:00–02:30 在线，桌面机意味着 Windows 重启就丢夜盘 —— 所以 `apps/recorder.py` 刻意与交易解耦，可单独跑在常开小主机上。**免费 1 分钟历史是整个项目最薄弱的一环，而唯一越来越好而不是越来越差的解法就是自己的档案。录一年是任何免费 API 都给不了的资产。**
2. **交易所官方文件**（SHFE/INE dailydata、DCE、CZCE、GFEX 日行情持仓）—— 免费、权威、永久 URL、日线粒度。这是**结算价、涨跌停、持仓量（定主力）**以及费率保证金变动通知的真相来源。绝不要只经封装库取而不存原始载荷。
3. **自己账户的 CTP 查询**（`ReqQryInstrumentCommissionRate` / `ReqQryInstrumentMarginRate` / `ReqQryInstrument`）—— **费率保证金的最佳来源，因为它返回的是含你券商加成的、对你生效的真实费率**，这是任何交易所页面都不会告诉你的（B4）。每日快照进 `raw/ctp_query/`，由 `meta/params.py` 从快照序列构建 SCD-2 表。注意流控（约 1 次/秒），且 `ReqQryInstrument` 返回几千行（C5）。
4. **TqSdk 免费档** —— 有多年分钟历史，适合一次性 bootstrap 回填。**只作 bootstrap**：免费条款与合约覆盖会变，拉一次落进 `raw/tqsdk/`，绝不让定时任务依赖它。
5. **AkShare** —— 方便、覆盖广、不稳定。它包装新浪/东财/交易所端点，会无预警失效，且分钟端点通常只返回近期若干日。用于日历、日线、补缺；每次响应都存快照；**绝不当真相**。
6. **券商快期/文华 CSV 导出** —— 手工、繁琐，但确实是拿多年分钟历史的合法一次性途径。值得在 Phase 4 花一个下午。

### 质量校验（R7/R8 的落地，含 D1 修正）

按 `(symbol, trading_day)` 跑，结果写质量台账并带严重级别：

| 检查 | 级别 | 真相来源 |
|---|---|---|
| Bar 数 vs `sessions(product, asof)` 应有分钟数 | <95% ERROR，其余 WARN | `meta/sessions` |
| dt 不在该品种当日任何时段内 | ERROR | `meta/sessions` |
| trading_day 与 `to_trading_day(dt)` 不符 | ERROR | `meta/calendar` |
| dt 重复 / OHLC 违背 / 价格非 price_tick 整数倍 | ERROR | `meta/contracts` |
| 价格超出涨跌停带 | ERROR | 交易所日文件 |
| 收盘价与交易所收盘价/结算价对不上超过 1 tick | ERROR | 交易所日文件 |
| **零成交分钟缺 Bar** | **仅当同期同品种主力有成交时才算真缺失**（D1） | 主力合约同分钟 |
| 成交量/持仓量出现不可能的递减 | WARN | — |

**发布闸门**：`qf data build` 拒绝换入含任何 ERROR 的 curated 分区，除非 `--allow-dirty`，且该越权记入台账。缺口检测是一等输出不是日志行 —— `qf data gaps --product rb --since 2020` 应打印一张可行动的表，因为**自录档案里缺口是常态失效模式，你需要知道哪些回测结论是站在窟窿上的**。

---

## 领域雷区的归属

这些全是业务逻辑，没有捷径，**加起来会消耗性能优化 10–50 倍的精力**。「先让它快」在这里是错的本能。

| 雷区 | 归属模块 | 关键点 |
|---|---|---|
| **平今/平昨** | `execution/offsets.py`（决策）+ `meta/params.py`（费率）+ `costs/fees.py`（钱） | 上期所/能源中心分别记今昨仓且**必须显式标平今**，发普通 CLOSE 会被拒或错用；大商所净持仓但费用区分；郑商所/广期所基本净持。部分品种平今近乎免费，部分是惩罚性的 → 决策必须**按费用比较**而非机械选择。回测必须收同样的钱（A3） |
| **夜盘归属交易日** | `meta/calendar.py`，只暴露一个函数 `to_trading_day(dt, exchange)` | 21:00–02:30 属**下一交易日**，周五夜盘属周一，节前夜盘整体停（不是顺延）。所有消费方（录制器、聚合、回测、实盘、日志命名、PnL 归集）只调这一个函数。**错了的表现很隐蔽：1 分钟 Bar 看着正常，但日线聚合、单日亏损限额、结算 PnL、"入场后第几根"全部静默出错** |
| **主力连续与换月复权** | `data/continuous/` | 两个产物分开：**换月映射**（trading_day → 活跃合约）与**复权序列**。换月规则用 T-1 数据决定 T 日、连续确认 1–2 日防抖、强制单向前滚。**用当日数据选当日合约是未来函数，会静默抬高每个回测**。复权方式偏差见下 |
| **郑商所 3/4 位年月** | `meta/symbols.py` | `MA509` 需参考日期才能定 2015 还是 2025，并用挂牌/到期窗口校验；**歧义时报 ERROR，绝不猜**。同时归属：品种代码大小写（郑商所大写、上期所小写）、组合/跨期代码（SPD/IPS）必须识别并**排除**出 Bar 构建 |
| **交易日历与各品种时段** | `meta/calendar.py` + `meta/sessions.parquet` | 免费来源：交易所年度放假通知（权威，每年 12 月发）、AkShare 交易日助手作种子、**以及自己录的数据**（观测到 tick 的日子定义上就是交易日）。时段**按品种随时间变化，必须 SCD-2**：夜盘曾被增设与取消、夜盘收盘时间有 23:00/01:00/02:30 之分、2020 年夜盘停过数月、集合竞价窗口各所不同。**一张硬编码的时段字典会静默毁掉全部历史 Bar 数校验** |
| **费率/保证金/最小变动价位/合约乘数** | `meta/params.py`，SCD-2 | 来源优先级：自己的 CTP 查询快照（最好，含券商加成）> 交易所通知 > 券商费率表。乘数和 tick 很少变但**会变**；保证金变动频繁。费用结构混合（元/手、按名义比例、平今差异、部分品种有申报费），`costs/fees.py` 需支持两种形态。**日内策略的边际利润常常就等于费用假设，所以 `--fee-multiplier 2` 敏感性测试应进标准报告** |
| **涨跌停 / 集合竞价 / 结算价** | `meta/` 存（源自交易所日文件）；`engines/fill.py` 与 `risk/checks.py` 执行 | 涨跌停：**封板假设完全不成交**（B7）——否则会恰在最大单边行情那几根凭空造利润；实盘 `risk/` 拦截穿越价带的委托。集合竞价：20:55–21:00 与 08:55–09:00 产生怪异成交量与单一价格，**决定一次并写进文档**：从序列中剔除、开盘 Bar 打标、绝不让信号在其上触发。结算价：每日盯市/追保/无负债结算用**结算价（加权均价）不是收盘价**（C2） |
| **合约到期与交割** | `runtime/`（新增，B1） | **这是清单里唯一会直接产生损失的缺失项。** 个人客户多数商品期货不能进交割。规则：到期前 N 个交易日强制平仓或换月（N 按品种配），临近到期禁开新仓，且要覆盖"策略还想持有"的情形 |
| **CTP 流控** | `gateway/ratelimit.py` | 令牌桶，在每个请求前施加：查询类约 1/秒（超了返回 -3 且 SDK 直接丢弃）、报单有券商上限、撤单次数被交易所监控（过量会被关注且有申报费）。`ReqQryInstrument` 很大，登录时只做一次。**限流器必须在网关里，不能散落在调用点**，否则一定在最糟的时刻撞上 |
| **断线重连后持仓对账** | `runtime/reconcile.py` | 每次连接、重连、交易日边界：查持仓/资金/委托/成交，与本地状态做差，**任何不符即冻结新报单 + 推手机 + 要求人工放行，永不自动纠正**（B3）。危险场景是报单已发未收回报时断线：本地说空仓、券商说多 2 手。缓解靠每个意图带 `client_id` 幂等键 + 只追加委托流水，重连后可问"我那笔 20250801-rb-0037 到了吗"而不是猜。注意 CTP 持仓查询分今昨返回，`YdPosition` 语义是经典陷阱 —— **对账要到今/昨级别，不只是净额** |
| **穿透式监管** | `gateway/compliance.py` + `conf/local.toml` | 需券商发的 AppID/AuthCode，以及机器标识采集（Windows 下是 vnpy_ctp 附带的采集库）。失效表现是登录被拒且错误码不直观，通常 20:59 才发现（C3）。做成**启动前置检查**：验采集库存在、验 AppID/AuthCode 非空、记录解析结果（绝不记密码），在开盘前大声失败 |

### 复权方式的偏差（必须显式选，`data/continuous/` 归属）

- **无复权**：每次换月有假跳空。抬高 ATR、制造假突破，趋势系统会"赚"到根本无法交易的跳空。做信号最差，但它是价格的诚实记录。
- **后复权**（锚在起点）：近端价格是真实可交易价，所以仓位计算、以 tick 计的止损距离、与实盘的一致性都成立。但远端价格会漂离现实，长历史大累计换月下**可能变负**，破坏任何对数收益或百分比逻辑。
- **前复权**（锚在今天）：历史连续且近端真实，**但每发生一次新换月，整条序列被重写** —— 三月跑的回测和四月在"同一份数据"上重跑结果不同。除非版本化冻结，否则不可复现（这正是 B5）。
- **比例复权**：避免负值且收益率有意义，但扭曲绝对价位，以 tick 为单位的止损和整数关口逻辑变得无意义。

**建议**：以逐合约原始 Bar 为真相来源；按需生成复权序列，**把规则与复权方式编进路径**（`cont/rule=oi_prev/adj=back/`）使每个结果可归因；产出 `roll_events` 表并在回测中于每个换月日**显式计费**（两腿手续费 + 1–2 tick 点差）。运行铁律：**绝不对连续合约代码报单** —— 连续序列只是信号输入，`runtime/` 必须先经换月映射解析到真实合约再交给 `execution/`。

---

## 跨模块工程约定（防冲突用，Phase 0 就要定）

模块边界解决的是"谁负责什么"。下面这些解决的是**"大家对同一个东西的说法必须一致"**—— 不定就会打架，而且多数是静默的。

### 1. 标识的单一规范形式（最高优先级）

同一个东西有多种写法，是这类系统最大的静默 bug 源。**每类标识只有一个规范形式，转换只在最边缘发生。**

| 东西 | 规范形式 | 转换点 |
|---|---|---|
| 合约 | `rb2510.SHFE`（品种小写按交易所惯例、4 位年月、带交易所后缀） | `meta/symbols.py` 的 `to_canonical()` / `to_wire(api=...)`，**仅此一处** |
| 连续合约 | `rb.MAIN@oi_prev:back`（规则与复权方式编进标识） | 同上。**绝不可用于报单** |
| 时间 | tz-aware `Asia/Shanghai`，**Bar 时间戳 = 分钟开始** | 数据源适配器入口转换并断言（B2） |
| 交易日 | `date`，经 `to_trading_day()` 得出，夜盘已前滚 | `meta/calendar.py`，唯一出口 |
| 方向/开平 | 自有枚举 `core/enums.py` | `engines/vnpy_bridge.py` 与 `gateway/` 转 vnpy 枚举 |
| 策略实例 | `(strategy_class, instance_name)`，重启后稳定 | 实例名进配置文件，不自动生成 |
| 委托 | `client_id`，格式 `{交易日}-{品种}-{序号}`，幂等键 | `runtime/state.py` 生成，只追加流水 |

**为什么值得单列**：`MA509` 到底是哪个合约、Bar 时间戳差一分钟、连续合约代码误入报单 —— 这三类错误的共同特征是**不报错、结果还更好看**。规范形式加边缘转换是唯一可靠的防法。

### 2. 配置 vs 参考数据的分界（这条与 R22.1 冲突，要改）

需求文档把手续费、保证金、交易时段都放进"配置文件"。**这是错的分类，会打架**：

- **市场事实**（费率、保证金率、交易时段、合约乘数、最小变动价位、交易日历、涨跌停幅度）→ **`meta/` 的带生效日期表**。它们随时间变化、有权威来源、回测必须用当时的值。放 conf 里意味着回测 2019 年用的是今天的保证金（B4）。
- **用户选择**（数据根路径、日志级别、风控上限、订阅清单、tick 白名单、券商账号、策略参数）→ **`conf/*.toml`**。它们没有"历史正确值"，是你的决定。

判据一句话：**"这个值在 2020 年有一个不同的正确答案吗？"** 有 → `meta/` 表；没有 → `conf/`。

### 3. 状态所有权（全自动下的安全关键）

每份状态**恰好一个所有者**，其他模块只读。两个模块都认为自己拥有持仓，就会发散。

| 状态 | 唯一真相 | 其他模块 |
|---|---|---|
| 实际持仓（含今/昨拆分） | **券商**（CTP 查询） | `runtime/state.py` 只是镜像；不符即冻结（B3） |
| 目标持仓 | 策略 | 执行层只读并负责收敛 |
| 委托生命周期 | 只追加的委托流水（`orders.jsonl`） | 内存里的视图可重建 |
| 账户权益/可用资金 | 券商 | 回测里由 `costs/` 计算 |
| 策略内部变量 | 策略自己，经 `get_state()` 导出 | `runtime/` 只负责存取，不解释内容 |
| 已落库数据的存在性 | 采集台账 + 来源表 | 不靠扫文件推断 |

### 4. 进程边界与写锁（会**真的**打架 —— 文件锁级别）

三个进程会同时活着：**录制器**（常驻）、**实盘进程**、**回测/研究**。DuckDB 跨进程是单写多读、写时持排他锁。不分清就会出现录制器拿不到锁而丢 tick。

| 进程 | 写什么 | 读什么 |
|---|---|---|
| 录制器 | `raw/**` Parquet（只追加、无锁）、`warehouse.duckdb` 的台账 | `meta/` |
| 构建任务（`qf data build`） | `curated/**`、`warehouse.duckdb` | `raw/**` |
| 实盘进程 | `runtime/state.db`、`orders.jsonl`、`snapshot.json` | `curated/` 读预热数据、`meta/` |
| 回测/研究 | 只写 `results/` | **`warehouse.duckdb` 必须以 read-only 打开** |
| 监控面板 | 什么都不写 | 只读 `snapshot.json` + `events.jsonl` |

两条硬规则：**录制器与构建任务不同时跑**（构建安排在收盘后）；**回测一律 read-only 连接**。Parquet 的原始层是只追加文件、不涉及锁，这也是选它而非单一数据库文件的一个附带理由。

### 5. 失败分类与停机策略（全自动的底线）

不分类的后果是：系统要么因琐事崩掉，要么带着严重故障继续交易。**后者会亏钱。**

| 类别 | 例子 | 策略 |
|---|---|---|
| **立即停机 + 推手机 + 人工放行** | 持仓对账不符、穿透式监管失败、风控模块自身异常、交易日历缺当天数据 | 绝不自动恢复 |
| **停该策略，其余继续** | 单个策略回调抛异常（R11.5 已有） | 记堆栈 |
| **拒绝并回灌策略** | 风控否决、资金不足、涨跌停拦截 | 必须让策略知道（D2） |
| **有界重试** | 写库失败、CTP 查询超时、行情重连 | **必须有上限 + 落地兜底**，不可无限重试（D4） |
| **记录并跳过** | 单条 tick 越界、单条外部数据字段缺失 | 计数型日志，不逐条告警（D1） |

`core/errors.py` 的异常类型与这张表一一对应，看类型就知道处理方式。

### 6. 测试夹具：一份冻结的黄金数据集

不建这个，每个模块会各自造测试数据，测试之间无法交叉印证，且没人敢改共用逻辑。

`tests/fixtures/` 放一小份**冻结不动**的真实数据，覆盖已知的所有坑：
- 一个含夜盘的完整交易日（跨自然日）
- 一个周五夜盘（归属周一）
- 一个节前夜盘停盘日
- 一个春节前后的交易日边界
- 一个郑商所 3 位年月合约
- 一次主力换月（含 `roll_events`）
- 一个涨跌停封板日
- 一个冷门合约的大量零成交分钟

配一个 `Clock` 抽象（可注入的时钟），否则夜盘边界、交易日切换、限流窗口这些都无法确定性测试。**策略禁止调 `datetime.now()`** 这条规则也依赖它。

每类持久化细节由状态所有者自己封装：`data` 只封装市场数据 SQL/路径，`meta` 封装参考事实，`runtime` 封装 `state.db` 与委托流水，`obs` 封装日志/快照/事件流。调用方只依赖公开端口；替换市场数据后端在组合根注入新实现，不设置一个可在运行期热切换的 `database.driver`。

### 7. schema 版本与数据版本戳

- **数据 schema 版本**写进 Parquet 文件元数据。改 Bar 字段时，旧分区要么仍可读、要么显式重建，不能静默错位。
- **数据版本戳**：每次 curated 构建产生一个版本号，回测报告带上它（这是 B5 可复现性的落点）。
- **策略状态 schema 版本**：`get_state()` 的字典带版本号，改字段时能识别旧状态。

### 8. 依赖钉死与 CTP 版本记录

`vnpy_ctp` 的 wheel 要匹配 Python 小版本，且 CTP API 因穿透式监管一路 6.3.x → 6.7.x → 7.x 变动。**钉死精确版本**，并在 `docs/` 记录当前用的 CTP 版本号与对应的采集库 —— 升级时这是唯一能对照的东西。

### 9. CLI 命名空间统一

前面示例里我混用了 `dp build` / `bt run` / `live run`。定成**一个入口 + 子命令**：

```
qf data ingest|build|cont|quality|gaps|show|params
qf bt   run|sweep|report
qf live run|status|flatten|recon|slippage
qf rec  start|status
```

小事，但不统一会导致脚本、文档、ADR 里的命令彼此对不上。

### 10. 版本控制（Phase 0 已完成 `git init`，这条直接关系到你要的多版本迭代）

你明确希望"迭代很多版本后让更强的模型来审视"——没有 git history，ADR 就失去了时间轴，审阅者也看不到设计是怎么演化的。Phase 0 已 `git init`（branch `main`，`core.autocrlf=false`）。

`.gitignore` 至少要含：`conf/local.toml`（账号密码、AppID/AuthCode，对应 R22.2/R22.3）、`data/`（运行期数据根）、`results/`、`__pycache__/`、`.venv/`。

配套：`conf/local.toml.template` 只留字段名与占位值进版本库（R22.3 已要求）。提交前检查不含凭证明文。

### 11. 数据资产备份（自录数据丢了买不回来）

这是整个项目里**唯一不可重建**的东西 —— 代码能重写，`curated/` 能从 `raw/` 重建，但 `raw/ctp_tick/` 里那些自己录的 tick 没了就永久没了。

- `raw/**` 定期同步到外部盘或对象存储（只追加，增量同步很便宜）
- `curated/**` 不必备份（可重建）
- `runtime/orders.jsonl` 与 `state.db` 要备份（对账凭据）
- 备份要**验证可读且校验和一致**，不是只看文件在不在：`raw/**` 对 Ingest_Manifest，`orders.jsonl` 与 `state.db` 对备份操作生成的 Backup_Manifest

放在 Phase 2 一起做 —— 那时才刚开始录，正是建立习惯的时候，而不是攒了一年后才想起来。

---

## 分阶段实施

每个阶段结束时都有**独立可用**的产出，即使就此停下也不白做。

### Phase 0 — 骨架（半天）

固定解释器（**64 位 CPython 3.13.11**，由 vnpy_ctp 的 wheel 矩阵决定，见 ADR-0014）、venv、装依赖（vnpy、vnpy_ctp、duckdb、pyarrow、polars、numpy、pandas、rich、typer、pydantic-settings、pytest、ruff、mypy、import-linter）。写 `pyproject.toml`、`.importlinter` 分层契约。

**同时建立文档骨架**（不能事后补 —— 决策当时的约束和否决理由，过两周就想不起来了）：`CLAUDE.md` 仓库地图、`docs/REVIEW_ME.md`、`docs/adr/INDEX.md`、各空包按固定模板的 `README.md` 存根，以及那条「README 公开接口 == `__all__`」的一致性测试。

**同时把「跨模块工程约定」9 条落成可执行的东西**（不是写成文档就算）：`core/enums.py` 与 `core/errors.py`（失败分类一一对应）、`core/timeutil.py` 的 `Clock` 抽象、`meta/symbols.py` 的规范形式转换骨架、`conf/` 与 `meta/` 的分界（判据：「这个值在 2020 年有不同的正确答案吗」）、进程写锁分工写进 `CLAUDE.md`、`qf` 单一 CLI 入口骨架、依赖精确钉死并记录 CTP 版本号。

**验证**：`tools/check.ps1` 一次通过（含 README 固定小节、公开接口、文件行数、系统时钟唯一出口与分层契约）；`lint-imports` 输出 `Contracts: 6 kept, 0 broken`；`python -c "import vnpy_ctp"` 成功；`tools/requirements_coverage.py` 能诚实输出尚未实施的验收标准。

### Phase 1 — `core` + `meta.calendar` + `meta.symbols`（刻意不含 I/O 与网络）

全项目正确性的地基。此阶段同时定义 `meta` 自有的 `Reference_Data_Store` Protocol 与
Trading_Session 值模型；纯逻辑通过注入的端口读取参考事实，不反向依赖 L3 的 `data`。
持久化适配与当前时段种子的加载留到 Phase 2。

**实现状态**：代码已完成（`meta/models.py`、`meta/store.py`、`meta/symbols.py`、
`meta/calendar.py`，加 `core` 新增的 `NotInTradingSession`）。算法与结构测试全绿；
**市场事实一类都还没核对**，全部以 `pending_expected` 失败着（R34.7），列在
`tests/meta/test_market_facts.py`，是本阶段唯一必须由人完成的部分。

**一处接口修订**：验证片段原写作 `to_trading_day(dt, SHFE)`（只按交易所查）。实际签名为
`to_trading_day(moment, exchange, product)` —— 夜盘的存在与否与收盘时间都因品种而异
（部分品种无夜盘，收盘 23:00 / 01:00 / 02:30 三档），只按交易所查会把这个事实抹平；
只按品种查又依赖"各所品种代码不重名"这一未核对的前提，所以两个键都要。`moment`
**必须带时区**，naive 输入直接拒绝；品种级时段缺失抛 `SessionSpecMissing`（记录并跳过），
日期超出日历覆盖才抛 `CalendarMissing`（停机）。

**验证**（前三项已由算法测试在合成日历上通过；后五项为待人工核对的市场事实）：
- `to_trading_day(moment, SHFE, "rb")` 对夜盘时间戳返回其后的第一个交易日，周五夜盘返回下周一
- 跨零点夜盘的尾段（凌晨）归属同一交易日；周五夜盘延续到周六凌晨时归属下周一
- 夜盘按公告停盘时该时段**不存在**，抛 `NotInTradingSession` 而非顺延
- `to_trading_day(2024-01-05 21:30, "rb") == 2024-01-08`（周五夜盘 → 周一）
- `to_trading_day(2024-02-08 21:00, "rb")` 返回停盘（春节夜盘整体停）
- `to_canonical("MA509", CZCE, asof=2025-06-01) == "MA2509.CZCE"`
- `to_canonical("MA509", CZCE, asof=2015-06-01) == "MA1509.CZCE"`
- `to_wire("MA2509.CZCE", "ctp") == "MA509"`

```powershell
.venv\Scripts\python.exe -m pytest tests/meta -m "not pending_expected" -q   # 必须全过
.venv\Scripts\python.exe -m pytest tests/meta -m pending_expected -q         # 必须全不全过
.venv\Scripts\python.exe tools\requirements_coverage.py --module meta
```

**独立价值**：你已经能可靠回答"这个时间戳属于哪个交易日"——免费生态里没有哪个库能替你做对。
**但不能上线**：这个答案目前建立在未核对的时段与日历上，填入真实数据前它只是自洽，不是正确。

### Phase 2 — CTP 连通 + tick 录制器 + `obs`（**立刻开始攒数据**）

`gateway/`（登录、穿透式前置检查、限流器、订阅）、`apps/recorder.py`、`obs/`（日志、快照、推送），加 `gateway/queries.py` 每日快照你的费率/保证金/合约表。**首次录制前的硬门槛**：将当前交易日历与各录制品种的 Trading_Session 种子加载进 `meta` 的 Reference_Data_Store，并由开发者依据交易所公告核对；覆盖范围外必须抛错，禁止靠工作日或硬编码时段猜测。

**排第二的理由**：数据档案是长周期项，**每推迟一周就永久少一周历史**。

**验证**：20:55 跑 `python -m apps.recorder --symbols rb2510,MA509`；21:05 时 `data/raw/ctp_tick/trading_day=.../rb2510.parquet` 存在、约 500 行、时间戳单调；另一终端 `python -m apps.monitor` 显示心跳与 tick 计数；**用 SIGKILL 杀掉监控，确认录制器继续写**（这条验证双进程隔离）；手机收到"录制器已启动，订阅 2 合约"；`data/raw/ctp_query/.../commission.parquet` 里是你的真实费率。

### Phase 3 — `data/` 存储、聚合、质量、vnpy DB 垫片

tick → 1 分钟（用 `meta.sessions`）、整分区 curated 构建、采集台账、**来源表**、质量检查、`data/vnpy_db.py`。

**验证**：`qf data build bar1m --day 20250801` → `qf data quality --day 20250801` 零 ERROR；`qf data show rb2510 --last 10` 的 Bar 数与 `expected_minutes` 相符；**关键**：`python -c "from vnpy.trader.database import get_database; print(len(get_database().load_bar_data(...)))"` 能通过垫片返回你的 Bar —— 这证明 vnpy 会在你的存储上回测。

### Phase 4 — 历史回填 + 合约/费率/换月映射 + 连续序列

一次性 TqSdk / 快期导出 / AkShare 回填进 `raw/`，交易所日文件采集，`meta/contracts.parquet` 与 `params.parquet` 建成 SCD-2，然后 `data/continuous/`。

**验证**：`qf data cont build rb --rule oi_prev --adj back --start 2019` 产出序列 + `roll_events` 表；有一条测试断言每个换月决策只用了 `trading_day < 换月日` 的数据（**未来函数守卫**）；`qf data gaps --product rb --since 2019` 打印诚实的缺口表；`qf data params rb2510 --asof 2023-06-01` 返回**当时**生效的费率保证金而不是今天的。

### Phase 5a — 多品种引擎实测选型（半天到一天，**不拍脑袋**）

对 `vnpy_portfoliostrategy` 和 `vnpy.alpha` 各跑一个最小期货例子，**验证保证金、合约乘数、手续费算得对不对**（`vnpy.alpha` 面向股票设计，期货支持未经验证）。

**验证**：给定 1 手 rb、已知乘数与保证金率，手算占用保证金，与引擎输出比对；故意让资金不足，看是否正确拒单。用实测结果决定 R13 走哪个引擎。

### Phase 5b — `strategy` + `indicators` + `engines/vnpy_bridge` + 首个真实回测（闭环）

Strategy ABC、SeriesView 环形缓冲、指标双形态、**一个刻意平庸的参考策略**（双均线或唐奇安通道）、桥、`engines/backtest.py` 接真实费用（含平今）与换月成本。

**验证**：`qf bt run dual_ma --product rb --start 2019 --end 2024` 输出夏普/最大回撤/成交笔数并写 `trades.parquet`；`pytest tests/indicators -q` 通过标量式与序列式在随机输入下的一致性；`grep -rn "^from\|^import" src/strategy/library/` **只应出现 core、indicators、strategy、numpy**；`qf bt run ... --fee-multiplier 2` 显示有多少利润其实来自费用假设。

### Phase 6 — `execution` + `risk` + `runtime` 在模拟环境

开平决策、目标持仓收敛、限价定价、风控筛查、实盘循环、状态持久化、对账、调度、**到期换月强平（B1）**。

模拟环境的定位：用 SimNow（7×24 环境可在任意时刻测完整会话生命周期）验证**管路** —— 登录、流控、委托生命周期、平今标志、重连、状态恢复。要清醒：**SimNow 的撮合不真实，它验证的是管路不是盈亏**。券商模拟账户是第二选择，同样的告诫。

**验证**：SimNow 上 `qf live run dual_ma --env simnow` 完成一次往返，且委托日志在上期所平仓腿显示 `CLOSE_TODAY` 而非普通 `CLOSE`；**恢复演练** —— 持仓中 `taskkill` 进程，重启，确认对账与券商持仓一致且零重复报单；**反向演练** —— 在快期里手工多开 1 手，重启，确认进程**冻结并推送告警**而不是继续交易（验证 B3）。

### Phase 7 — 真钱，1 手，1 品种，硬熔断

同一套代码 `--env real`，`max_position=1`，单日亏损限额设成你会不在意的数。

**验证**：实盘跑一周，然后 `qf live slippage --since <date>` 对比建模与实际成交价、建模与实际手续费。**如果手续费对不上几个百分点以内，说明 `costs/fees.py` 或 `meta/params.py` 是错的，Phase 5b 的一切都是虚构。这份报告是整个系统真正的验收测试。**

### Phase 8 — 只在 Phase 7 已经无聊了一个月后：`engines/loop.py` + 滚动前推

**验证**：边界测试 —— 同一策略文件、同一数据，`engines/backtest.py` 与 `engines/loop.py` 产出一致的成交清单与 PnL（浮点误差内），且 loop 快 20 倍以上。**这个相等性就是"策略可移植契约"真的成功了的证明。** 之后参数扫描与滚动前推才划得来。

参数扫描用 multiprocessing/joblib（按物理核心数，绕开 GIL），搜索用 optuna 而非暴力网格。**这里是 CPU 多核吃满的地方，不是 GPU。**

### 阶段与需求的对应

| Phase | 覆盖 requirements.md |
|---|---|
| 1 | R3（部分）、C4 |
| 2 | R1、R2、R4、R20、R21、R22、C3、C5 |
| 3 | R5、R6、R7、R8、A4、A5、D1、D4 |
| 4 | R9、R10、C1、C2、B4、B5 |
| 5a/5b | R11、R12、R13、R14、A1、A2、A3、B2、B7 |
| 6 | R16、R17、R18、R19、R23、B1、B3、B6、D2、D3 |
| 7 | 全链路验收 |
| 8 | R15、R25 |

---

## 最可能让项目失败或亏钱的 5 件事

**1. 回测结果撑不过实盘 —— 主要经由费用和连续合约偏差。**
这是最可能亏钱的路径，而且在亏之前一直看起来像成功。具体机制：平今费未建模、换月未计费、前复权序列在两次运行间被静默重写、用当日持仓量决定当日主力、涨跌停封板仍假设成交、以收盘价而非结算价盯市。
*已内建的缓解*：回测与实盘共用同一个 `costs/fees.py` 且接收同一个已解析 offset；显式 `roll_events` 并计费；规则与复权方式编进产物路径使结果可归因；换月映射的未来函数守卫测试；悲观的 `engines/fill.py`；以及 Phase 7 用 1 手真钱做的费用/滑点对账报告——它会抓住前面漏掉的一切。

**2. 回测与实盘因策略 API 本身而分裂。**
经典形态：策略读 `position()`，回测里是同步真值，实盘里是延迟的、部分的、异步的。
*缓解*：目标持仓作为主接口；**一个**桥同时服务回测与实盘，没有第二份实现可以漂移；`position()` 文档标注为仅供诊断；Phase 8 的跨引擎相等性测试作为常驻回归。

**3. 凌晨 2 点无人看守时的运维失效。**
持仓中断线、Windows 自动更新导致错过夜盘、卡住的未确认委托、重连后重复报单、磁盘满导致进程死亡。
*缓解*：连接时对账并在不符时**冻结**（永不自动纠正）；`client_id` 幂等键 + 只追加委托流水；写者/读者分离的快照使监控绝无可能拖垮交易进程；每次状态转移推手机；跨收盘边界的持有或平仓策略显式化；录制器刻意可单独跑在常开机器上。

**4. 过拟合 —— 造出一台能从稀薄档案里生产"看起来合理的边缘"的机器。**
免费 1 分钟历史短且有洞，60,000ms 决策周期下 3 年补丁般的数据并不是很多独立观测。这也是**现在不做 ML** 的根本理由。
*缓解*：Phase 2 起自建录制使样本随时间增长；缺口表作为一等输出，让你知道哪些结论站在窟窿上；`--fee-multiplier 2` 敏感性进标准报告；滚动前推推迟到 Phase 8，使你在能交易一个策略之前无法扫参数；实施顺序强制**恰好一个平庸策略**先走通到真钱。

**5. 单人项目的头号杀手：一个永远不上线的半成品系统。**
14 个模块、一个数据仓库、一个向量化引擎，都比"一个真会报单的 1 手双均线"更好玩。**过度模块化是同一种失败换了身好衣服。**
*已内建*：每个阶段独立有用（Phase 2 单独就在积累数据资产，Phase 3 单独就给你可查询的档案）；合并优先于拆分且明确列出拒绝的拆分；不做 GUI 不做图表（看盘交给快期/文华）；网关这类脏活交给 vn.py；自研引擎放在 Phase 8 而不是诱人的 Phase 2。

还有第六个不必渲染但要点名的：单机、单券商、单网络的单点故障。个人规模下没有聪明的设计解法。诚实的缓解是一台常开的上海机房小主机、仓位小到全程断网仍可承受、以及一条硬规则——**不持有你不愿意在糟糕价格上发现的仓位**。

---

## 需要同步修改 requirements.md

上述 24 项修订需要回写进 `.kiro/specs/vnpy-futures-trading-system/requirements.md`。改动量最大的几条：

- **R11.1** 重写（策略基类改为纯逻辑类 + 适配器）
- **R12.4 / R17.5** 重写（自建费用模块，回测实盘共用）
- **R6 / R9.6** 增加来源表与双接口
- **R23.1 / R23.6** 改为双进程
- **R18.6** 改为冻结而非自动纠正
- **新增需求**：合约到期与交割强平、结算价、主力连续与复权、穿透式监管前置检查、CTP 查询流控、Bar 时间戳定义
- **R25.4 / R25.7** 容量方案改为 tick 走 Parquet
- **R24.5** 缩小 EventEngine 适用范围（仅异步推送）

建议做法：先按本计划改 requirements.md 定稿，再开 Phase 0。**需求文档是本项目的真相来源，本计划只是修订依据。**

---

## 端到端验证方式

| 层级 | 怎么验 |
|---|---|
| 单模块 | `pytest tests/<module> -q`，秒级返回。日历与代码规范化用手工核对的表驱动用例 |
| 分层约束 | `lint-imports` 零违规（对应 R24.7）；`grep -rn "^from\|^import" src/strategy/library/` 只出现 core/indicators/strategy/numpy |
| 文档不说谎 | 每个 README 的「公开接口」小节与该模块 `__all__` 完全一致（测试强制）；ADR 引用无悬空、被取代的 ADR 不再被生效文档引用 |
| 数据正确性 | `qf data quality --day <日期>` 零 ERROR；`qf data gaps` 缺口表；换月映射未来函数守卫测试；`qf data params <合约> --asof <历史日期>` 返回当时费率 |
| vnpy 集成 | 通过 `data/vnpy_db.py` 垫片能被 `get_database().load_bar_data()` 读到（Phase 3 的关键验证） |
| 引擎选型 | Phase 5a 手算保证金与引擎输出比对 |
| 策略可移植性 | Phase 8 跨引擎成交清单与 PnL 相等 |
| 实盘管路 | SimNow 完整往返 + 上期所平仓腿显示 `CLOSE_TODAY`；kill 后重启对账零重复报单；手工制造持仓不符后确认进程冻结告警 |
| 最终验收 | **Phase 7 的 `qf live slippage` 报告：实盘一周，建模手续费与实际对不上几个百分点以内则前面全是虚构** |
