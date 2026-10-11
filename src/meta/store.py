"""参考数据端口 —— meta 自己拥有的读取契约(R3.1)。

**为什么是 Protocol 而不是抽象基类**:消费方(`calendar`、`data`、`execution`)只依赖
方法签名,不 import 任何实现;实现方(Phase 2 的 Parquet/DuckDB 适配器、Phase 3 的
测试替身)只提供数据,**不含任何交易日判定逻辑**。判定逻辑只有 `meta.calendar`
一处(R3.4)—— 这正是本端口只返回原始记录、不提供「下一个交易日」这类派生方法的原因:
一旦端口提供派生方法,每个实现都会写出略有差异的换日规则。

**为什么端口在 meta 而不在 data**:交易日历、时段、费率是"某日期下的市场参考事实",
与 L3 的市场数据存储是两回事。若 `meta` 从 `data` 读取,是 L2 反向依赖 L3,
`.importlinter` 的分层契约当场破裂,且回测路径会被迫拖进行情存储。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from core import Exchange
from meta.models import TradingDayRecord, TradingSessionSpec

__all__ = ["ReferenceDataStore"]


@runtime_checkable
class ReferenceDataStore(Protocol):
    """参考事实的读取契约。

    实现须保证:同一入参重复调用返回相同结果(纯查询,无隐式状态推进)。
    """

    def coverage(self) -> tuple[date, date]:
        """返回交易日历覆盖的闭区间 `(最早, 最晚)`。

        调用方据此判断能否回答某个日期,并在区间之外抛 `CalendarMissing` 而不是
        返回推测值(R3.13)。**这个区间必须来自数据本身**,不得由实现方写死常量:
        写死会让日历缺口的判定退化为"实现方以为覆盖到哪"。
        """
        ...

    def trading_days(self, start: date, end: date) -> Sequence[TradingDayRecord]:
        """返回 `[start, end]` 内按日期升序排列的交易日记录。

        非交易日不出现在结果中。调用方保证区间已落在 `coverage()` 之内 ——
        越界检查由 `meta.calendar` 统一完成,避免每个实现各写一遍。

        返回 `Sequence` 而非迭代器:调用方需要按序取首个与末个元素。
        """
        ...

    def session_spec(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        """返回该品种在 `asof` 生效的时段定义(R3.3)。

        键是 `(exchange, product)`,`product` 一律为**大写**品种代码:大写归一使
        `rb` 与 `RB` 命中同一份定义,交易所则防止跨所重名的品种互相串用时段。

        Raises:
            SessionSpecMissing: 该品种在 asof 无生效的时段定义。属「记录并跳过」类:
                缺的是一个品种的配置,不应冻结全部品种(R32.7)。**不得回退到最近的
                可用版本** —— 用今天的夜盘收盘时间解释 2019 年的 Bar,会让应有
                Bar 数与真实缺口同时算错,而 1 分钟序列看起来完全正常。
        """
        ...
