"""参考事实的形态定义 —— 交易时段与交易日的结构。

这些类型只承载**形态**,不含"哪些日期是交易日""夜盘几点收"这类市场事实:
后者来自交易所公告,由 Reference_Data_Store 提供,其测试预期值须人工核对(R34.4)。

**结构不变式放在值类型上,与 `core/types.py` 的取舍相反**,理由是二者的错法不同:
`Bar` 的 OHLC 是否合法随上下文变化(质量检查要保留异常记录,回测要拒单),
所以校验不能塞进类型;而时段定义的重叠或退化**没有上下文相关的正确解释**,
任何一种读法都会让应有的 Bar 数静默算错,故在此就地拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from itertools import pairwise

from core import Exchange

__all__ = [
    "SessionKind",
    "SessionWindow",
    "TradingDayRecord",
    "TradingSessionSpec",
]

_MINUTES_PER_DAY = 24 * 60


class SessionKind(StrEnum):
    """Trading_Session 的类别(R3.1/R3.12)。

    CALL_AUCTION 与 DAY/NIGHT 分开而不是并入 DAY,是因为集合竞价的成交形态特殊:
    R5.11 要求把它排除在 Bar 序列之外。若并入 DAY,08:55–09:00 那段会被当成
    连续交易时段计入应有 Bar 数,使每天的质量检查凭空多出 5 分钟缺口。
    """

    DAY = "day"
    NIGHT = "night"
    CALL_AUCTION = "call_auction"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """一个连续的时段区间,以当日本地时刻表示。

    **跨零点用 `end < start` 表达**(夜盘 21:00–02:30),不拆成两个窗口。跨零点
    区间在时间轴上有两段:本自然日的 [start, 24:00) 与前一日延续下来的
    [00:00, end)。因此判定必须区分 `covers_head` 与 `covers_tail` —— 同样是
    01:00,落在哪一段决定了它属于哪个交易日。
    """

    kind: SessionKind
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.end == self.start:
            raise ValueError(
                f"时段区间长度为 0({self.start})。零长度区间覆盖不到任何时刻,"
                f"使应有 Bar 数少算且不报错;停盘应通过不声明该窗口表达。"
            )

    @property
    def crosses_midnight(self) -> bool:
        """区间是否跨过零点。< 而非 <=:等长区间已在 __post_init__ 拒绝。"""
        return self.end < self.start

    @property
    def start_minute(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_minute(self) -> int:
        """归一到 0–2880,使跨零点区间可直接参与重叠比较。"""
        end = self.end.hour * 60 + self.end.minute
        return end + _MINUTES_PER_DAY if self.crosses_midnight else end

    def duration_minutes(self) -> int:
        """区间长度(分钟)。"""
        return self.end_minute - self.start_minute

    def covers_head(self, clock: time) -> bool:
        """时刻是否落在**本自然日开始**的那一段。

        左闭右开:区间结束的那一分钟不属于本区间(10:15 收盘则 10:15 已不在内)。
        """
        if self.crosses_midnight:
            return clock >= self.start
        return self.start <= clock < self.end

    def covers_tail(self, clock: time) -> bool:
        """时刻是否落在**前一自然日开始、延续到本自然日**的那一段。"""
        return self.crosses_midnight and clock < self.end


@dataclass(frozen=True, slots=True)
class TradingSessionSpec:
    """某品种在一段生效期内的时段定义(R3.1/R3.2)。

    同一品种在不同历史时期可以有不同定义 —— 夜盘曾被增设与取消,收盘时间有
    23:00 / 01:00 / 02:30 之分。因此本类型带 `effective_from` / `effective_to`,
    查询必须给参考日期,不存在"当前时段"这一概念。
    """

    exchange: Exchange
    """所属交易所 —— 与 `product` 共同构成时段定义的键。

    保留交易所是因为"各交易所品种代码大写后互不重名"这一前提从未被核对。若只按品种
    查而两所恰好重名,一个品种会静默用上另一个品种的夜盘收盘时间。
    """

    product: str
    """**大写**品种代码。

    与大写归一而不与 Canonical_Symbol 的品种大小写一致,是为了让查询天然
    大小写无关:`rb` 与 `RB` 若各存一份定义,两版的夜盘收盘时间可以不同,
    而查询结果取决于调用方写法,这类不一致不报错且极难定位。
    """

    effective_from: date
    #: None 表示至今仍生效。开放上界是必须的:最后一个版本没有结束日期。
    effective_to: date | None
    windows: tuple[SessionWindow, ...]

    def __post_init__(self) -> None:
        if self.product != self.product.upper():
            raise ValueError(
                f"时段定义的品种键必须大写,收到 {self.product!r};"
                f"大小写混用会让同一品种存在两份可生效的定义"
            )
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError(
                f"{self.product} 的生效期上界 {self.effective_to} 早于下界 "
                f"{self.effective_from};两版时段会同时生效,查询结果不确定"
            )
        spans = sorted((w.start_minute, w.end_minute) for w in self.windows)
        for (_, previous_end), (next_start, _) in pairwise(spans):
            if next_start < previous_end:
                raise ValueError(
                    f"{self.product} 的时段区间重叠(下一段起于第 {next_start} 分钟,"
                    f"上一段止于第 {previous_end} 分钟)。重叠区间会让同一时刻命中两个"
                    f"窗口,交易日归属与应有 Bar 数都不再唯一"
                )

    def covers(self, asof: date) -> bool:
        """本定义在 asof 是否生效。"""
        if asof < self.effective_from:
            return False
        return self.effective_to is None or asof <= self.effective_to

    def windows_of(self, kind: SessionKind) -> tuple[SessionWindow, ...]:
        return tuple(window for window in self.windows if window.kind is kind)

    @property
    def day_windows(self) -> tuple[SessionWindow, ...]:
        """日盘区间。可能多段 —— 上午 09:00–10:15、10:30–11:30 与下午 13:30–15:00。"""
        return self.windows_of(SessionKind.DAY)

    @property
    def night_windows(self) -> tuple[SessionWindow, ...]:
        """夜盘区间。空元组表示该品种无夜盘。"""
        return self.windows_of(SessionKind.NIGHT)

    @property
    def call_auction_windows(self) -> tuple[SessionWindow, ...]:
        """集合竞价区间(R3.12)。夜盘与日盘各有一段,故返回元组。"""
        return self.windows_of(SessionKind.CALL_AUCTION)


@dataclass(frozen=True, slots=True)
class TradingDayRecord:
    """一个交易日,以及它是否以夜盘开始(R3.7)。

    `preceded_by_night_session` 是**外部公告事实**,不可由日历推导:周五夜盘归属
    下周一(跨三个自然日,照常开市),而节前最后一个交易日的夜盘整体停盘(次日
    即休市)。两种情形都不能从"次日是否为交易日"算出来,必须由交易所公告给出。

    默认为 False 是刻意的保守取向:漏记一个夜盘会让该时段的时间戳被判为"不在
    任何时段内"并计入计数型日志;反过来误记则会给不存在的时间戳分配交易日,
    直接污染日线聚合与单日亏损限额,且不报错。
    """

    day: date
    preceded_by_night_session: bool = False
