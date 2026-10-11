# core   (层级:L0)

## 职责

全系统共享词汇:值类型、枚举、异常分类、Clock 抽象。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

- `CHINA_TZ`
- `AdjustmentMethod`
- `Bar`
- `CalendarMissing`
- `Clock`
- `CompliancePreflightFailed`
- `ConfigInvalid`
- `Direction`
- `Disposition`
- `Exchange`
- `Fill`
- `HaltRequired`
- `InsufficientFunds`
- `Interval`
- `ManualClock`
- `NotInTradingSession`
- `Offset`
- `OrderIntent`
- `PriceLimitBlocked`
- `QfError`
- `ReconcileMismatch`
- `Rejected`
- `RetriesExhausted`
- `Retryable`
- `RiskCheckFailed`
- `RiskVetoed`
- `SessionSpecMissing`
- `Severity`
- `Skipped`
- `StrategyFailure`
- `SymbolAmbiguous`
- `SystemClock`
- `Tick`
- `ensure_aware`

## 不变式

- **`Bar.dt` 是该分钟的起始时刻**,不是结束时刻(R5.2)。破坏后果:整条序列错位
  一分钟,等于回测偷看未来,**且结果只会变好看**,因此不会被绩效指标发现。
  外部数据源的约定各家不同,转换与断言必须在 `data/` 的导入适配器完成(R10.6)。
- **`Bar.trading_day` / `Tick.trading_day` 必须经 `meta.calendar` 的唯一映射函数得出**,
  不得由 `dt.date()` 推导(R3.4)。夜盘 21:00–02:30 归属**其后**的交易日,周五夜盘
  归属下周一。绕过它的表现极其隐蔽:1 分钟 Bar 看起来完全正常,但日线聚合、
  单日亏损限额、结算 PnL、「入场后第几根」全部静默出错。
- **全部值类型为 frozen。** 值类型被共享后被就地修改,是难以定位的一类 bug。
- **`OrderIntent.offset` 到达 `execution/` 之外时必须已解析。** 上期所与能源中心
  的平仓须显式标平今或平昨,发普通 `CLOSE` 会被拒或错用(R17.7)。
- **`OrderIntent.volume` 必为正整数。** 小于 1 手或非整数在回测与实盘均被拒(R12.12)。
- **`Tick.volume` 与 `Tick.turnover` 是当日累计值,不是本次增量。** 作差在
  `Bar_Aggregator` 完成(R5.7)。误当增量会使成交量被整体高估若干个量级。
- **异常类型与 R32 的五类处置方式一一对应**(R32.2)。捕获方只看类型即可决定
  停机、停策略、回灌、重试或计数跳过,不必读抛出点上下文。
- **`core/timeutil.py` 是全系统唯一允许调用系统时钟的位置**(R33.2)。
- **`NotInTradingSession` 属「记录并跳过」而非「立即停机」**(R3.10/R32.7)。
  越界时间戳在盘前盘后是常态,全市场录制下每天命中大量;若归入停机类,第一次
  收到 08:59 的行情就会冻结整个系统。它与 `CalendarMissing` 的分工是:后者表示
  日历数据没覆盖到该日期,属需人工放行的数据缺陷,不会自行恢复。
- **`SessionSpecMissing` 同属「记录并跳过」**(R32.7)。缺的是单个品种的时段配置,
  停机会用一个品种的遗漏换全市场的数据损失。但跳过不等于无声:被跳过的行情无法
  补录,调用方必须按品种汇总计数并告警。
- **`ensure_aware` 对 naive 输入按北京时间补齐,只适用于数据源入口。** 判定交易日
  的 `meta.calendar` 直接拒绝 naive 时间戳:到那里还不带时区,说明上游的转换点漏了,
  而按北京时间猜会把 UTC 时刻静默错开 8 小时。

## 禁止 import

- **不得 import 任何交易框架(vnpy 及其插件)** —— L0 被所有层依赖,一旦引入框架
  即等于全系统锁死在该框架上(ADR-0004)。
- **不得 import pandas / polars / duckdb / pyarrow** —— 值类型须可在向量化引擎内
  逐根构造,DataFrame 的构造开销与之不相容。
- **不得 import 磁盘、网络、交易所规则、券商相关的任何内容** —— L0 之下无层可依赖。

## 为什么这么设计

值类型刻意保持"笨":只承载字段,不含校验与业务规则。理由是校验的正确判据随
上下文变化 —— 质量检查按 R8 判定 OHLC 违背,回测按 R12.12 判定手数,把规则塞进
类型会让两处需求争夺同一个位置,且其中一处必然是错的。

异常层级按**处置方式**而非按**发生位置**划分。按位置划分(`DataError` /
`GatewayError`)的问题是:捕获方拿到 `DataError` 仍然不知道该重试还是该停机,
必须回去读抛出点。按处置方式划分则使 R32 的五类策略可由类型直接确定。

## 否决过的方案

- **用 vnpy 的 `BarData` / `TickData` 作为共享类型。** 最省事,但 `BarData` 无任何
  来源字段(A4),而 R6.11 要求记录每条 Bar 的数据来源 —— 这是「自建数据资产为主」
  这条核心原则能否落地的技术前提。且引入它会使 L0 依赖 vnpy,违反上一节。
- **给值类型加 `__post_init__` 校验(OHLC 关系、手数为正)。** 否决理由见上:
  同一份数据在质量检查阶段需要"保留异常记录并标记"(R8.10),在回测阶段需要
  "拒绝并记录原因"(R12.12)。构造即抛错会使前者无法实现。
- **异常按模块划分。** 见上一节。
- **Clock 用 `time.time()` 返回 float 时间戳。** 省去时区问题,但夜盘跨自然日的
  归属判断需要日期语义,float 时间戳会把每个使用点都变成一次手工转换。

## 已知局限

- **Phase 8 的向量化引擎若需复用可变 Bar 对象以避免每根分配**,须在 `engines/`
  内部另设可变表示,不放宽本模块的 frozen 约束。届时策略侧会看到"Bar 对象是
  临时的"这一按设计的泄漏,须写进 `strategy/README.md`。
- `Tick` 目前只保留一档盘口。扩展订单流研究(R25.15)时需扩为五档,届时须同时
  提升 Parquet 的 schema 版本号(R6.12)以使旧分区不被静默错读。
- `Bar.is_session_open` 是布尔标记,无法表达"该 Bar 属于哪个 Session"。若将来
  需要按 Session 分段统计,应改为 Session 序号。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/core -q
```
