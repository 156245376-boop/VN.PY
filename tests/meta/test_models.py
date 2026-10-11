"""参考事实值模型的结构不变式。

这些用例的预期值全部由类型定义本身推得,不涉及市场事实:重叠的时段区间、倒置的
生效期、大小写不一致的品种键在任何数据下都是错误的,因此可以就地断言。

为什么这些不变式值得测试:`TradingSessionSpec` 的调用方有五个以上(录制器、
聚合器、质量检查、回测、实盘)。若定义里躺着一个重叠区间,每个调用方都会得到
略有不同的答案,而 1 分钟 Bar 序列**看起来完全正常**。
"""

from __future__ import annotations

import dataclasses
from datetime import date, time

import pytest

from core import Exchange
from meta import SessionKind, SessionWindow, TradingDayRecord, TradingSessionSpec

pytestmark = pytest.mark.covers("R3.1", "R3.2")

VALUE_TYPES = [SessionWindow, TradingSessionSpec, TradingDayRecord]


@pytest.mark.parametrize("cls", VALUE_TYPES, ids=lambda item: item.__name__)
def test_value_types_are_frozen_and_slotted(cls: type) -> None:
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "__slots__" in cls.__dict__


def test_session_window_rejects_zero_length() -> None:
    """零长度区间覆盖不到任何时刻,会让应有 Bar 数少算且不报错。"""
    with pytest.raises(ValueError, match="长度为 0"):
        SessionWindow(SessionKind.DAY, time(9, 0), time(9, 0))


@pytest.mark.parametrize(
    ("start", "end", "crosses", "minutes"),
    [
        (time(9, 0), time(10, 15), False, 75),
        (time(21, 0), time(23, 0), False, 120),
        (time(21, 0), time(2, 30), True, 330),
        (time(21, 0), time(1, 0), True, 240),
    ],
)
def test_session_window_duration_and_midnight_crossing(
    start: time, end: time, crosses: bool, minutes: int
) -> None:
    window = SessionWindow(SessionKind.NIGHT if crosses else SessionKind.DAY, start, end)
    assert window.crosses_midnight is crosses
    assert window.duration_minutes() == minutes


@pytest.mark.parametrize(
    ("clock", "in_head", "in_tail"),
    [
        (time(8, 59), False, False),
        (time(9, 0), True, False),  # 起点含
        (time(10, 14), True, False),
        (time(10, 15), False, False),  # 终点不含
    ],
)
def test_non_crossing_window_is_left_closed_right_open(
    clock: time, in_head: bool, in_tail: bool
) -> None:
    window = SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15))
    assert window.covers_head(clock) is in_head
    assert window.covers_tail(clock) is in_tail


@pytest.mark.parametrize(
    ("clock", "in_head", "in_tail"),
    [
        (time(20, 59), False, False),
        (time(21, 0), True, False),  # 晚间起点
        (time(23, 59), True, False),
        (time(0, 0), False, True),  # 次日凌晨属尾段
        (time(2, 29), False, True),
        (time(2, 30), False, False),  # 收盘时刻已不在内
        (time(10, 0), False, False),
    ],
)
def test_crossing_window_separates_head_and_tail(
    clock: time, in_head: bool, in_tail: bool
) -> None:
    """同一时刻只能落在头段或尾段之一 —— 决定它属于哪个交易日。"""
    window = SessionWindow(SessionKind.NIGHT, time(21, 0), time(2, 30))
    assert window.covers_head(clock) is in_head
    assert window.covers_tail(clock) is in_tail


def _spec(**overrides: object) -> TradingSessionSpec:
    kwargs: dict[str, object] = {
        "exchange": Exchange.SHFE,
        "product": "RB",
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
        "windows": (SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15)),),
    }
    kwargs.update(overrides)
    return TradingSessionSpec(**kwargs)  # type: ignore[arg-type]


def test_overlapping_windows_are_rejected() -> None:
    """重叠会让同一时刻命中两个窗口,交易日归属与应有 Bar 数都不再唯一。"""
    with pytest.raises(ValueError, match="重叠"):
        _spec(
            windows=(
                SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15)),
                SessionWindow(SessionKind.DAY, time(10, 0), time(11, 0)),
            )
        )


def test_adjacent_windows_are_allowed() -> None:
    """上午两段之间是休息,不是重叠 —— 误判会把正常时段定义挡在门外。"""
    spec = _spec(
        windows=(
            SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15)),
            SessionWindow(SessionKind.DAY, time(10, 30), time(11, 30)),
        )
    )
    assert len(spec.day_windows) == 2


def test_inverted_effective_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="生效期上界"):
        _spec(effective_from=date(2020, 1, 1), effective_to=date(2019, 1, 1))


def test_lowercase_product_key_is_rejected() -> None:
    """键一律大写,否则 `rb` 与 `RB` 各存一份定义且查询结果取决于写法。"""
    with pytest.raises(ValueError, match="必须大写"):
        _spec(product="rb")


@pytest.mark.parametrize(
    ("asof", "expected"),
    [
        (date(2019, 12, 31), False),
        (date(2020, 1, 1), True),
        (date(2021, 1, 1), True),
    ],
)
def test_open_ended_effectivity_covers_all_later_dates(asof: date, expected: bool) -> None:
    assert _spec().covers(asof) is expected


def test_closed_effectivity_stops_at_upper_bound() -> None:
    spec = _spec(effective_from=date(2020, 1, 1), effective_to=date(2020, 12, 31))
    assert spec.covers(date(2020, 12, 31)) is True
    assert spec.covers(date(2021, 1, 1)) is False


def test_window_selection_by_kind() -> None:
    spec = _spec(
        windows=(
            SessionWindow(SessionKind.CALL_AUCTION, time(8, 55), time(9, 0)),
            SessionWindow(SessionKind.DAY, time(9, 0), time(10, 15)),
            SessionWindow(SessionKind.CALL_AUCTION, time(20, 55), time(21, 0)),
            SessionWindow(SessionKind.NIGHT, time(21, 0), time(2, 30)),
        )
    )
    assert len(spec.day_windows) == 1
    assert len(spec.night_windows) == 1
    assert len(spec.call_auction_windows) == 2


def test_product_without_night_session_has_empty_night_windows() -> None:
    assert _spec().night_windows == ()


def test_trading_day_record_defaults_to_no_night_session() -> None:
    """默认保守:漏记夜盘只会让该时段被计为越界,误记则会凭空分配交易日。"""
    record = TradingDayRecord(day=date(2024, 1, 8))
    assert record.preceded_by_night_session is False


def test_trading_day_record_rejects_nothing_beyond_fields() -> None:
    """值模型只承载字段:交易日是否真的开市属外部事实,不在此处校验。"""
    assert [field.name for field in dataclasses.fields(TradingDayRecord)] == [
        "day",
        "preceded_by_night_session",
    ]
