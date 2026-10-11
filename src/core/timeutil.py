"""时区常量与 Clock 抽象(R33.1–R33.3)。

**本模块是全系统唯一允许调用系统时钟的位置**(R33.2)。其他模块一律经注入的
Clock 取时间,理由是夜盘边界、交易日切换、限流窗口这些逻辑若依赖真实当前
时间,就只能在对应时刻才能测 —— 等于不可测。

策略侧另有一条更严的约束:策略连 Clock 都不碰,时间由引擎经 Strategy_Context
供给(R11.6),因为回测中的「当前时间」是 Bar 时间而非真实时间。
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

__all__ = [
    "CHINA_TZ",
    "Clock",
    "ManualClock",
    "SystemClock",
    "ensure_aware",
]

#: 全系统统一时区(R10.9)。国内期货的交易日与夜盘归属均以此为基准。
CHINA_TZ: tzinfo = ZoneInfo("Asia/Shanghai")


@runtime_checkable
class Clock(Protocol):
    """时间源协议。

    实现须返回 tz-aware 的 datetime —— naive datetime 在夜盘跨自然日的场景下
    无法判断归属,且与 Bar 时间戳比较时会静默抛错或错算。
    """

    def now(self) -> datetime:
        """返回当前时间,带 CHINA_TZ 时区信息。"""
        ...


class SystemClock:
    """真实时间源。生产运行期使用。"""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(tz=CHINA_TZ)


class ManualClock:
    """可注入、可推进的时间源。测试专用(R33.3)。

    同时覆盖 R33.3 的两种要求:不调用 advance 即为固定时间,调用则可推进。
    """

    __slots__ = ("_now",)

    def __init__(self, start: datetime) -> None:
        self._now = ensure_aware(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """向前推进并返回新的当前时间。"""
        self._now += delta
        return self._now

    def set(self, moment: datetime) -> None:
        """直接设定当前时间。允许回拨,以便构造乱序场景。"""
        self._now = ensure_aware(moment)


def ensure_aware(moment: datetime) -> datetime:
    """将 naive datetime 视为 CHINA_TZ 本地时间补齐时区;已带时区的转换到 CHINA_TZ。

    转换点集中在此,是为了让「时间戳到底是哪个时区」这个问题在系统内只有一个答案。
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=CHINA_TZ)
    return moment.astimezone(CHINA_TZ)
