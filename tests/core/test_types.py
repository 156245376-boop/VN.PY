"""core 值类型的设计不变式。

本文件的预期值由实现方写定,不适用 R34.6 的人工核对要求 —— 它断言的是本项目
**自有的设计约定**(frozen、字段语义),而非市场事实。需要外部权威资料核对的是
交易日映射与合约代码推断,那些在 tests/meta 下并标记 pending_expected。
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime

import pytest

from core import (
    CHINA_TZ,
    Bar,
    Direction,
    Exchange,
    Fill,
    Interval,
    Offset,
    OrderIntent,
    Tick,
)

VALUE_TYPES = [Bar, Tick, OrderIntent, Fill]


def make_bar(**overrides: object) -> Bar:
    kwargs: dict[str, object] = {
        "symbol": "rb2510.SHFE",
        "exchange": Exchange.SHFE,
        "interval": Interval.MINUTE,
        "dt": datetime(2024, 1, 5, 21, 30, tzinfo=CHINA_TZ),
        "trading_day": date(2024, 1, 8),
        "open": 3500.0,
        "high": 3510.0,
        "low": 3495.0,
        "close": 3505.0,
        "volume": 120.0,
        "turnover": 4_206_000.0,
        "open_interest": 25_000.0,
    }
    kwargs.update(overrides)
    return Bar(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("cls", VALUE_TYPES, ids=lambda c: c.__name__)
def test_value_types_are_frozen(cls: type) -> None:
    """全部值类型不可变 —— 值类型被共享后被就地修改是难以定位的一类 bug。"""
    params = dataclasses.fields(cls)
    assert params, f"{cls.__name__} 应为 dataclass"
    assert cls.__dataclass_params__.frozen, (  # type: ignore[attr-defined]
        f"{cls.__name__} 必须为 frozen dataclass(见 src/core/README.md 不变式)"
    )


@pytest.mark.parametrize("cls", VALUE_TYPES, ids=lambda c: c.__name__)
def test_value_types_use_slots(cls: type) -> None:
    """使用 slots:全市场录制下 Bar 与 Tick 的构造量在每年十亿量级。"""
    assert "__slots__" in cls.__dict__, f"{cls.__name__} 应声明 slots"


def test_bar_rejects_mutation() -> None:
    bar = make_bar()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = 9999.0  # type: ignore[misc]


def test_bar_trading_day_is_independent_of_calendar_date() -> None:
    """夜盘 Bar 的 trading_day 与自然日不同,故必须是独立字段而非由 dt 推导。

    这里只断言"能表达",不断言映射规则是否正确 —— 映射规则属 meta.calendar,
    其预期值须经外部资料核对(R33.6)。
    """
    bar = make_bar(
        dt=datetime(2024, 1, 5, 21, 30, tzinfo=CHINA_TZ),
        trading_day=date(2024, 1, 8),
    )
    assert bar.dt.date() != bar.trading_day


def test_bar_defaults_to_not_session_open() -> None:
    """开盘标记默认关闭 —— 忘记设置时的后果应是少一个标记,而非凭空多一个。"""
    assert make_bar().is_session_open is False


def test_tick_volume_field_documents_cumulative_semantics() -> None:
    """Tick.volume 是当日累计值。误当增量会使成交量高估若干个量级(R5.7)。"""
    doc = Tick.__doc__ or ""
    assert "累计" in doc, "Tick 的累计量语义必须写在 docstring 里 —— 它是一个易错点"


def test_order_intent_carries_resolved_offset_and_client_id() -> None:
    """委托意图须携带已解析的开平标志与幂等键。"""
    intent = OrderIntent(
        client_id="20240108-rb-0037",
        symbol="rb2510.SHFE",
        exchange=Exchange.SHFE,
        direction=Direction.SHORT,
        offset=Offset.CLOSE_TODAY,
        volume=2,
        price=3500.0,
        strategy_name="dual_ma_rb",
    )
    assert intent.offset is not Offset.CLOSE, (
        "到达 execution 之外的意图不得携带未解析的 CLOSE —— 上期所会拒单或错用(R17.7)"
    )
    assert intent.client_id.startswith("20240108-"), "幂等键须以交易日开头(R17.2)"


def test_fill_commission_defaults_to_zero() -> None:
    """成交的手续费默认 0,由 costs 显式填入 —— 缺省值不应假装已计费。"""
    fill = Fill(
        client_id="20240108-rb-0037",
        symbol="rb2510.SHFE",
        exchange=Exchange.SHFE,
        direction=Direction.SHORT,
        offset=Offset.CLOSE_TODAY,
        price=3500.0,
        volume=2,
        dt=datetime(2024, 1, 8, 9, 1, tzinfo=CHINA_TZ),
        trading_day=date(2024, 1, 8),
    )
    assert fill.commission == 0.0
