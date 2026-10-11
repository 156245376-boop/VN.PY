"""Clock 抽象与时区处理(R33.1–R33.3)。

预期值由实现方写定:本文件断言的是 Clock 协议的行为契约,不涉及市场事实。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core import CHINA_TZ, Clock, ManualClock, SystemClock, ensure_aware

pytestmark = pytest.mark.covers("R33.1", "R33.2", "R33.3")


def test_system_clock_satisfies_protocol() -> None:
    """SystemClock 与 ManualClock 须可互换 —— 否则注入无意义。"""
    assert isinstance(SystemClock(), Clock)
    assert isinstance(ManualClock(datetime(2024, 1, 5, 21, 30)), Clock)


def test_system_clock_returns_aware_china_time() -> None:
    """naive datetime 在夜盘跨自然日时无法判断归属,故必须带时区。"""
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=8)


def test_manual_clock_does_not_advance_on_its_own() -> None:
    """固定时间源:同一时刻的多次读取必须相等,否则测试不可复现。"""
    clock = ManualClock(datetime(2024, 1, 5, 21, 30))
    assert clock.now() == clock.now()


def test_manual_clock_advance_crosses_calendar_day(clock: ManualClock) -> None:
    """夹具时刻为 2024-01-05 21:30(周五夜盘)。推进 5 小时跨过自然日边界。

    这是夜盘归属逻辑必须处理的场景:自然日变了,交易日不该跟着变。
    """
    before = clock.now()
    after = clock.advance(timedelta(hours=5))
    assert after == before + timedelta(hours=5)
    assert after.date() != before.date()
    assert clock.now() == after


def test_manual_clock_set_allows_rewind() -> None:
    """允许回拨 —— 用于构造乱序 Tick 等场景。"""
    clock = ManualClock(datetime(2024, 1, 8, 9, 1))
    clock.set(datetime(2024, 1, 5, 21, 0))
    assert clock.now().date().day == 5


def test_manual_clock_normalizes_naive_input() -> None:
    """naive 入参按本地时间补齐,不抛错 —— 测试里手写时间戳应当省事。"""
    clock = ManualClock(datetime(2024, 1, 5, 21, 30))
    assert clock.now().tzinfo is not None
    assert clock.now().hour == 21


def test_ensure_aware_treats_naive_as_local() -> None:
    naive = datetime(2024, 1, 5, 21, 30)
    assert ensure_aware(naive) == datetime(2024, 1, 5, 21, 30, tzinfo=CHINA_TZ)


def test_ensure_aware_converts_other_timezone() -> None:
    """已带时区的输入转换到 CHINA_TZ,而非替换 tzinfo —— 后者会静默改变时刻。"""
    utc_moment = datetime(2024, 1, 5, 13, 30, tzinfo=UTC)
    converted = ensure_aware(utc_moment)
    assert converted.hour == 21
    assert converted.utcoffset() == timedelta(hours=8)
    assert converted == utc_moment


def test_ensure_aware_is_idempotent() -> None:
    moment = datetime(2024, 1, 5, 21, 30, tzinfo=CHINA_TZ)
    assert ensure_aware(ensure_aware(moment)) == ensure_aware(moment)
