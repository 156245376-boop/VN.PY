"""共享值类型 —— 全系统传递数据的词汇表。

这些类型刻意保持"笨":只承载字段,不含校验与业务规则。理由是校验的正确判据
随上下文变化(质量检查按 R8 判定 OHLC 违背,回测按 R12.12 判定手数),把规则
塞进类型会让两处需求争夺同一个位置。

全部为 frozen —— 值类型被共享后被就地修改,是难以定位的一类 bug。

已知局限:Phase 8 的向量化引擎若需复用可变对象以避免每根 Bar 分配,须在
engines/ 内部另设可变表示,不放宽本模块(见 strategy/README.md 的"泄漏"第 1 条)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core.enums import Direction, Exchange, Interval, Offset

__all__ = ["Bar", "Fill", "OrderIntent", "Tick"]


@dataclass(frozen=True, slots=True)
class Bar:
    """1 分钟 K 线。

    **dt 是该分钟的起始时刻**(R5.2/B2):dt=09:01 的 Bar 覆盖 09:01:00–09:01:59.999。
    这条约定必须钉死,因为外部数据源各家不同,而混用会使整条序列错位一分钟
    —— 等于回测偷看未来,且结果只会变好看。外部源的转换与断言在
    History_Import_Adapter 完成(R10.6)。

    trading_day 经 meta.calendar 的唯一映射函数得出,夜盘 Bar 已前滚(R5.3)。
    """

    symbol: str
    """Canonical_Symbol,含交易所后缀,例如 rb2510.SHFE(R27.1)。"""

    exchange: Exchange
    interval: Interval
    dt: datetime
    """分钟起始时刻,tz-aware。"""

    trading_day: date

    open: float
    high: float
    low: float
    close: float

    volume: float
    """该分钟内成交量,由累计量作差得出(R5.7)。"""

    turnover: float
    open_interest: float
    """该分钟最后一条 Tick 的持仓量(R5.8)。"""

    is_session_open: bool = False
    """是否为某个 Trading_Session 的首个 Bar(R5.11)。

    集合竞价行情已被排除在序列之外,该标记用于让策略避免在开盘 Bar 上触发信号。
    """


@dataclass(frozen=True, slots=True)
class Tick:
    """CTP 行情快照。

    **不是逐笔成交**:国内期货推送间隔约 500ms,单个快照周期内的多笔成交被合并。
    任何依赖逐笔序列的逻辑(真实订单流、成交方向推断)在此数据上不成立。

    volume 与 turnover 为**当日累计值**,不是本次增量 —— 作差在 Bar_Aggregator
    完成(R5.7)。
    """

    symbol: str
    exchange: Exchange
    dt: datetime
    trading_day: date

    last_price: float
    volume: float
    """当日累计成交量。"""

    turnover: float
    """当日累计成交额。"""

    open_interest: float

    bid_price_1: float = 0.0
    bid_volume_1: float = 0.0
    ask_price_1: float = 0.0
    ask_volume_1: float = 0.0

    limit_up: float = 0.0
    limit_down: float = 0.0
    """交易所公布的当日涨跌停价。封板时回测假设完全不成交(R12.4/B7)。"""


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """一笔待提交的委托意图。

    由 execution/ 从目标持仓差额解析产生,不由策略直接构造 —— 策略表达目标持仓,
    不表达委托(ADR-0003)。策略确需挂单或停止单时经逃逸接口提交,并须标记自身
    不可向量化(R11.5)。

    offset 到达此处时**必须已解析**:上期所与能源中心的平仓须显式标平今或平昨,
    发普通 CLOSE 会被拒或错用(R17.7)。解析决策依费率高低而非机械选择(R17.8)。
    """

    client_id: str
    """幂等键,格式 {交易日}-{品种}-{序号}(R17.2)。

    断线重连后据此判定「我那笔委托到了吗」,而不是猜(R18.14)。
    """

    symbol: str
    exchange: Exchange
    direction: Direction
    offset: Offset
    volume: int
    """手数。必为正整数 —— 小于 1 手或非整数在回测与实盘均被拒(R12.12)。"""

    price: float
    """限价委托价格,已按涨跌停区间钳制(R17.10)。"""

    strategy_name: str
    """发出该意图的策略实例名,用于把拒单与成交回灌给正确的实例(R17.11)。"""


@dataclass(frozen=True, slots=True)
class Fill:
    """一笔成交回报。

    commission 由 costs/fees.py 计算,回测与实盘调用同一函数(R29.1/R29.8)。
    该同一性是防止回测与实盘分裂的机制 —— 也是本项目最可能亏钱的路径上的
    主要缓解手段。
    """

    client_id: str
    symbol: str
    exchange: Exchange
    direction: Direction
    offset: Offset
    price: float
    volume: int
    dt: datetime
    trading_day: date
    commission: float = 0.0
