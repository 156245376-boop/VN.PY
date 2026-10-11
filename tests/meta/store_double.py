"""测试用的 ReferenceDataStore 替身。

**本文件只搬运表,不含任何交易日判定逻辑** —— 判定逻辑只有 `meta.calendar` 一处
(R3.4)。若替身自己实现"下一个交易日",测试就会用被测逻辑去验证被测逻辑。

合成日历的用途是验证**算法**:给定这份日历,某时间戳应得到某个交易日。它不声称
现实中的哪一天是交易日 —— 那是外部权威资料,由 `pending_expected` 用例承担(R34.4)。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta

from core import CHINA_TZ, Exchange, SessionSpecMissing
from meta import (
    ReferenceDataStore,
    SessionKind,
    SessionWindow,
    TradingDayRecord,
    TradingSessionSpec,
)


def cst(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """构造带北京时间时区的时刻。交易日判定拒绝 naive 时间戳,测试也不例外。"""
    return datetime(year, month, day, hour, minute, tzinfo=CHINA_TZ)


class TableReferenceDataStore(ReferenceDataStore):
    """从内存表读取参考事实。"""

    def __init__(
        self,
        *,
        coverage: tuple[date, date],
        trading_days: Sequence[TradingDayRecord] = (),
        session_specs: Sequence[TradingSessionSpec] = (),
    ) -> None:
        self._coverage = coverage
        self._days = tuple(sorted(trading_days, key=lambda record: record.day))
        self._specs = tuple(session_specs)

    def coverage(self) -> tuple[date, date]:
        return self._coverage

    def trading_days(self, start: date, end: date) -> Sequence[TradingDayRecord]:
        return tuple(record for record in self._days if start <= record.day <= end)

    def session_spec(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        for spec in self._specs:
            if spec.exchange is exchange and spec.product == product and spec.covers(asof):
                return spec
        raise SessionSpecMissing(
            f"替身表里没有 {exchange.value}.{product} 在 {asof} 生效的时段定义"
        )


def weekday_calendar(
    start: date,
    end: date,
    *,
    holidays: Iterable[date] = (),
    suspended_night: Iterable[date] = (),
) -> tuple[TradingDayRecord, ...]:
    """构造一份"周一至周五为交易日"的合成日历。

    `holidays` 移出交易日;`suspended_night` 标记某交易日的夜盘按公告停盘
    (对应节前夜盘整体停,而非顺延)。
    """
    skipped = set(holidays)
    suspended = set(suspended_night)
    records: list[TradingDayRecord] = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in skipped:
            records.append(
                TradingDayRecord(day=day, preceded_by_night_session=day not in suspended)
            )
        day += timedelta(days=1)
    return tuple(records)


def rb_session_spec(
    *,
    effective_from: date,
    effective_to: date | None = None,
    night_close: time | None = None,
    exchange: Exchange = Exchange.SHFE,
    product: str = "RB",
) -> TradingSessionSpec:
    """构造一份与上期所螺纹钢形状相同的合成时段定义。

    形状取自常识以避免"忘记声明某个窗口"的错误,但它**不是**对交易时段的断言:
    真实时段须依据交易所公告核对,见 test_market_facts.py 的 pending_expected 用例。
    """
    windows = [
        SessionWindow(SessionKind.CALL_AUCTION, time(8, 55), time(9, 0)),
        SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15)),
        SessionWindow(SessionKind.DAY, time(10, 30), time(11, 30)),
        SessionWindow(SessionKind.DAY, time(13, 30), time(15, 0)),
    ]
    if night_close is not None:
        windows.append(SessionWindow(SessionKind.CALL_AUCTION, time(20, 55), time(21, 0)))
        windows.append(SessionWindow(SessionKind.NIGHT, time(21, 0), night_close))
    return TradingSessionSpec(
        exchange=exchange,
        product=product,
        effective_from=effective_from,
        effective_to=effective_to,
        windows=tuple(windows),
    )
