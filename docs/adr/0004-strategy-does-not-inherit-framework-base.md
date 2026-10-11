# ADR-0004:策略不继承交易框架基类,经 Engine_Adapter 适配

状态: 生效
日期: 2026-08-30
承重性: **承重** —— 决定 `strategy/` 的 import 闭包与 `engines/` 的存在理由。
推翻会使"更换回测引擎无需改动策略源码"(R11.9)不再可能

## 背景

`requirements.md` 的初稿(修订前的 R11.1)要求每个策略继承 `CtaTemplate`。这是
`vnpy_ctastrategy` 的标准用法,文档与示例都如此。

但同一份需求的 R11.9 要求"更换 Backtest_Engine 时不修改任何策略源文件"。这两条
不能同时成立:继承关系是编译期绑定,基类换掉就是每个子类都要改。

一项源码事实决定了适配层的形态:`vnpy_ctastrategy` 的回测与实盘用的是**同一个**
`CtaTemplate`(`vnpy_ctastrategy/template.py`)。所以桥只需要一个,不是两个。

## 决策

策略是纯逻辑类,继承系统自有的 `Strategy` ABC,import 闭包只含
`core` / `indicators` / `strategy` / `numpy`(R11.2)。

`CtaTemplate` 降为薄适配器 `engines/vnpy_bridge.py`(约 80 行),它同时继承
`CtaTemplate` 与实现 `StrategyContext` 协议,是**全项目唯一同时依赖 vnpy 与
Strategy 的文件**(R11.7)。

## 理由

**核心理由:框架基类会把整个框架拖进策略的 import 闭包,而闭包是传染的。**

继承 `CtaTemplate` 意味着策略文件顶部有 `from vnpy_ctastrategy import CtaTemplate`。
于是每个策略都依赖 vnpy;于是策略的测试需要 vnpy;于是 research notebook 里
复算一个信号也要装 vnpy。这些成本单看都不大,合起来是"锁死"的实际含义。

**这条约束的价值在于它可机械验证**,不依赖纪律:

```powershell
$env:PYTHONUTF8 = "1"; .venv\Scripts\lint-imports.exe
```

`.importlinter` 的 `strategy-no-framework` 契约禁止 `strategy` 导入 vnpy 及其插件、
以及 pandas / polars / duckdb / pyarrow(R24.13)。违反在提交前就会失败,而不是在
换引擎那天才发现。这属 ADR-0001 分级中的第一级(确定性检查)。

**桥只有一个,这一点必须坚持。** vnpy 回测与实盘共用同一个 `CtaTemplate`,故一个
适配器同时服务两边。拆成"回测桥"与"实盘桥"会招致两份实现各自漂移,而**分裂正是
回测实盘不一致的头号来源** —— 这也是本项目最可能亏钱的路径。

## 放弃的方案

- **策略直接继承 `CtaTemplate`。** 最省事,且是框架的推荐用法。否决理由如上,
  另加一条独立的硬约束:`BacktestingEngine.set_parameters` 只接收单个 `vt_symbol`
  (`vnpy_ctastrategy/backtesting.py:114` 实测),多品种组合回测(R13)在这条路上
  做不到 —— 即便不考虑可移植性,也必须有适配层。
- **回测与实盘各写一个适配器。** 看起来更清晰(各自只管一边),实际上因 vnpy 两边
  共用同一个 `CtaTemplate`,这个"清晰"是虚构的:两份代码做同一件事,然后开始
  分歧。见上一节。
- **不定义 `Strategy` ABC,靠鸭子类型约定 `on_bar` 存在。** 少一层继承,但失去
  `warmup_bars` / `vectorizable` 这类声明式元数据的位置,且拼错方法名时的表现是
  静默不触发而非报错。
- **用 `Protocol` 而非 ABC 定义策略侧。** `Protocol` 用在**引擎供给策略**的方向
  (`StrategyContext`)是对的 —— 那里需要策略对任何引擎零运行期依赖。但策略侧需要
  共享 `on_start` / `on_stop` 等可选方法的默认空实现,ABC 更合适。两个方向用不同
  机制是刻意的。

## 后果

好的方面:

- `strategy/` 的 import 闭包可机械验证,不依赖纪律
- 策略测试与 research notebook 不需要 vnpy
- 更换引擎的成本集中在一个文件(`engines/vnpy_bridge.py`),而非每个策略

坏的方面:

- **`engines/vnpy_bridge.py` 是全项目风险最集中的文件。** 它同时承担类型转换、
  预热边界换算、交易日切换回调、目标持仓收敛。它的缺陷会同时影响回测与实盘,
  且不表现为报错。Phase 8 的跨引擎一致性测试(R33.8)是针对它的主要防线。
- **多一层间接。** 读一个策略的完整行为需要同时读策略文件与桥。缓解手段是把桥
  控制在 400 行以内(R24.11)并在 `engines/README.md` 记录按设计的泄漏清单。
- **预热边界必然有偏差:** vnpy 的 `load_bar(days=N)` 按自然日,而 `warmup_bars`
  按根数,跨节假日无法精确换算。故判据是 `series.inited` 而非数根数(R11.17)。

## 相关

- ADR-0003 决定策略以目标持仓表达意图,二者共同构成"策略可移植契约"
- ADR-0010 决定自建环形缓冲而非复用 vnpy 的 `ArrayManager`,理由同属本条的
  import 闭包考虑
- 需求 R11.2 定义策略源码允许的导入依赖
- 需求 R11.7 要求 Engine_Adapter 是唯一同时依赖框架与 Strategy 的位置
- 需求 R24.13 要求该约束由依赖检查脚本强制
