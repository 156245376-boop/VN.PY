"""交易日判定的算法测试(R3.4–R3.14)。

**本文件用合成日历,不声称现实中的哪一天是交易日。** 断言的是:给定这份日历与
这份时段定义,某时间戳应得到某个交易日。合成日历里"周一至周五为交易日""元旦休市"
是**测试输入**,不是对市场的断言 —— 真实日历属外部权威资料,由
`tests/meta/test_market_facts.py` 的 `pending_expected` 用例承担(R34.4)。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from core import CalendarMissing, Exchange, NotInTradingSession, SessionSpecMissing, Skipped
from meta import ReferenceDataStore, SessionKind, TradingCalendar, TradingSessionSpec
from store_double import TableReferenceDataStore, cst, rb_session_spec, weekday_calendar

pytestmark = pytest.mark.covers(
    "R3.3",
    "R3.4",
    "R3.5",
    "R3.6",
    "R3.7",
    "R3.8",
    "R3.9",
    "R3.11",
    "R3.12",
    "R3.13",
    "R3.14",
)

SHFE = Exchange.SHFE
COVERAGE = (date(2023, 12, 1), date(2024, 12, 31))
SYNTHETIC_HOLIDAYS = frozenset({date(2024, 1, 1)})
SPEC_FROM = date(2000, 1, 1)

#: 2024-01-01 周一休市,01-02 周二起为交易日,01-05 为周五,01-06/07 为周末,
#: 01-08 为下周一。夜盘 21:00–02:30 跨零点。
TRADING_DAYS = weekday_calendar(COVERAGE[0], COVERAGE[1], holidays=SYNTHETIC_HOLIDAYS)
SPEC = rb_session_spec(effective_from=SPEC_FROM, night_close=time(2, 30))
STORE = TableReferenceDataStore(
    coverage=COVERAGE, trading_days=TRADING_DAYS, session_specs=(SPEC,)
)
CALENDAR = TradingCalendar(STORE)

#: 2024-01-08 的夜盘按公告停盘(模拟节前夜盘整体停,而非顺延)。
SUSPENDED_CALENDAR = TradingCalendar(
    TableReferenceDataStore(
        coverage=COVERAGE,
        trading_days=weekday_calendar(
            COVERAGE[0],
            COVERAGE[1],
            holidays=SYNTHETIC_HOLIDAYS,
            suspended_night={date(2024, 1, 8)},
        ),
        session_specs=(SPEC,),
    )
)

#: 日盘三段合计 225 分钟;夜盘 21:00–02:30 为 330 分钟。
DAY_MINUTES = 75 + 60 + 90
NIGHT_MINUTES = 330


class _NonCoveringStore(TableReferenceDataStore):
    """模拟"取到的时段定义不覆盖所查日期"的数据缺陷。"""

    def session_spec(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        return rb_session_spec(effective_from=date(2030, 1, 1), night_close=time(2, 30))


class _WrongProductStore(TableReferenceDataStore):
    """模拟"存储返回了别的品种的定义"的数据缺陷。"""

    def session_spec(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        return rb_session_spec(effective_from=SPEC_FROM, product="HC")


# ---------------------------------------------------------------------------
# R3.4–R3.7:时间戳 → 交易日
# ---------------------------------------------------------------------------


def test_day_session_timestamp_maps_to_its_own_calendar_day() -> None:
    assert CALENDAR.to_trading_day(cst(2024, 1, 8, 10), SHFE, "rb") == date(2024, 1, 8)


def test_night_session_maps_to_the_following_trading_day() -> None:
    """R3.5:夜盘归属其后的第一个交易日。"""
    assert CALENDAR.to_trading_day(cst(2024, 1, 8, 21, 30), SHFE, "rb") == date(2024, 1, 9)


def test_friday_night_maps_to_next_monday() -> None:
    """R3.6:周五夜盘归属下一周的第一个交易日,而不是下一个自然日。"""
    assert date(2024, 1, 5).weekday() == 4, "前提:2024-01-05 是周五"
    assert CALENDAR.to_trading_day(cst(2024, 1, 5, 21, 30), SHFE, "rb") == date(2024, 1, 8)


def test_night_session_tail_after_midnight_keeps_the_same_trading_day() -> None:
    """跨零点窗口的尾段仍属同一个交易日 —— 这是 Bar 时间戳归属最容易错的一处。"""
    assert CALENDAR.to_trading_day(cst(2024, 1, 9, 1), SHFE, "rb") == date(2024, 1, 9)


def test_night_tail_landing_on_a_weekend_still_belongs_to_friday_night_owner() -> None:
    """周五夜盘延续到周六凌晨,归属仍是下周一 —— 此时自然日反而不是交易日。"""
    assert date(2024, 1, 6).weekday() == 5, "前提:2024-01-06 是周六"
    assert CALENDAR.to_trading_day(cst(2024, 1, 6, 1), SHFE, "rb") == date(2024, 1, 8)


def test_suspended_night_session_is_absent_rather_than_shifted() -> None:
    """R3.7:停盘的夜盘时段**不存在**,不顺延到节后。"""
    with pytest.raises(NotInTradingSession, match="停盘"):
        SUSPENDED_CALENDAR.to_trading_day(cst(2024, 1, 5, 21, 30), SHFE, "rb")


@pytest.mark.parametrize(
    "moment",
    [
        cst(2024, 1, 8, 8),  # 集合竞价之前
        cst(2024, 1, 8, 15, 30),  # 日盘收盘之后
        cst(2024, 1, 8, 20),  # 夜盘集合竞价之前
        cst(2024, 1, 6, 10),  # 周六日盘时间
        cst(2024, 1, 1, 21, 30),  # 休市日晚间:没有夜盘
        cst(2024, 1, 1, 20, 57),  # 休市日夜间竞价:随夜盘一起停
    ],
)
def test_timestamps_outside_all_sessions_are_rejected(moment: datetime) -> None:
    """R3.10 的前提:越界时间戳必须能被识别出来,而不是拿到一个看似合理的交易日。

    后两个用例针对一类具体错误:夜盘(及其竞价)在节假日当晚不存在,若实现漏掉
    "时段只能起于交易日"这道检查,节假日 21:30 会被分配给节后第一个交易日。
    """
    with pytest.raises(NotInTradingSession):
        CALENDAR.to_trading_day(moment, SHFE, "rb")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (cst(2024, 1, 8, 8, 57), date(2024, 1, 8)),  # 日盘竞价 → 当日
        (cst(2024, 1, 8, 20, 57), date(2024, 1, 9)),  # 夜盘竞价 → 下一交易日
    ],
)
def test_call_auction_is_attributed_to_the_session_it_precedes(
    moment: datetime, expected: date
) -> None:
    """竞价行情不进 Bar 序列(R5.11),但它确实到达,仍需能归属到交易日以便记账。"""
    assert CALENDAR.to_trading_day(moment, SHFE, "rb") == expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2024, 1, 8, 2, 0, tzinfo=UTC), date(2024, 1, 8)),  # 北京 10:00
        (datetime(2024, 1, 8, 13, 30, tzinfo=UTC), date(2024, 1, 9)),  # 北京 21:30
    ],
)
def test_aware_timestamp_is_converted_to_china_time_zone(
    moment: datetime, expected: date
) -> None:
    """其他时区的时刻按北京时间判定。UTC 13:30 是北京时间夜盘,归属下一交易日。"""
    assert CALENDAR.to_trading_day(moment, SHFE, "rb") == expected


def test_naive_timestamp_is_rejected_instead_of_guessed() -> None:
    """时区转换只应发生在数据源入口(R10.6)。

    回归用例:早期实现把 naive 输入按北京时间补齐,于是一个 naive 的 UTC 13:30
    (实为北京时间 21:30 的夜盘)被归到当天,而不是下一个交易日,且不报错。
    """
    with pytest.raises(ValueError, match="不带时区"):
        CALENDAR.to_trading_day(datetime(2024, 1, 8, 13, 30), SHFE, "rb")


def test_product_lookup_is_case_insensitive() -> None:
    """`rb` 与 `RB` 必须命中同一份时段定义,否则查询结果取决于写法。"""
    moment = cst(2024, 1, 8, 21, 30)
    assert CALENDAR.to_trading_day(moment, SHFE, "rb") == CALENDAR.to_trading_day(
        moment, SHFE, "RB"
    )


def test_same_product_code_on_another_exchange_does_not_share_sessions() -> None:
    """时段定义按「交易所 + 品种」查,不得跨所串用。

    "各交易所品种代码大写后互不重名"从未被核对。若只按品种查,两所重名时一个品种会
    静默用上另一个品种的夜盘收盘时间。
    """
    with pytest.raises(SessionSpecMissing):
        CALENDAR.to_trading_day(cst(2024, 1, 8, 10), Exchange.DCE, "rb")


# ---------------------------------------------------------------------------
# R3.9 / R3.13 / R32.7:日历覆盖、品种缺失与处置类别
# ---------------------------------------------------------------------------


def test_is_trading_day_distinguishes_holiday_from_session() -> None:
    assert CALENDAR.is_trading_day(date(2024, 1, 2)) is True
    assert CALENDAR.is_trading_day(date(2024, 1, 1)) is False, "合成元旦休市"
    assert CALENDAR.is_trading_day(date(2024, 1, 6)) is False, "周六"


def test_dates_outside_calendar_coverage_raise_instead_of_guessing() -> None:
    """R3.13:超出覆盖范围抛错。返回推测值会让聚合与亏损限额静默错位。"""
    with pytest.raises(CalendarMissing):
        CALENDAR.is_trading_day(date(2023, 11, 30))
    with pytest.raises(CalendarMissing):
        CALENDAR.to_trading_day(cst(2023, 11, 30, 10), SHFE, "rb")


def test_night_session_near_the_coverage_edge_raises_instead_of_ending_calendar() -> None:
    """覆盖用尽 != 没有下一个交易日。二者混淆会让节后第一天的夜盘静默消失。"""
    last_day = max(record.day for record in TRADING_DAYS)
    with pytest.raises(CalendarMissing):
        CALENDAR.to_trading_day(
            cst(last_day.year, last_day.month, last_day.day, 21, 30), SHFE, "rb"
        )


def test_unconfigured_product_is_skipped_not_halted() -> None:
    """R32.7:缺一个品种的时段配置只跳过该品种,不得冻结全市场。

    若归入停机类,录制器收到一个未配置品种的行情就会停下全部品种,而自录 tick
    丢了买不回来。日期超出日历覆盖(上面的用例)才是停机类。
    """
    with pytest.raises(SessionSpecMissing) as caught:
        CALENDAR.to_trading_day(cst(2024, 1, 8, 10), SHFE, "cu")
    assert isinstance(caught.value, Skipped)
    assert not isinstance(caught.value, CalendarMissing)


@pytest.mark.parametrize("store_class", [_NonCoveringStore, _WrongProductStore])
def test_store_returning_a_mismatched_definition_is_rejected(
    store_class: type[TableReferenceDataStore],
) -> None:
    """R3.2:不得回退到最近的可用版本,也不得接受别的品种的定义。"""
    calendar = TradingCalendar(store_class(coverage=COVERAGE, trading_days=TRADING_DAYS))
    with pytest.raises(SessionSpecMissing):
        calendar.to_trading_day(cst(2024, 1, 8, 10), SHFE, "rb")


# ---------------------------------------------------------------------------
# R3.8 / R3.11 / R3.12:查询面
# ---------------------------------------------------------------------------


def test_is_in_session_agrees_with_to_trading_day() -> None:
    assert CALENDAR.is_in_session("rb2510.SHFE", cst(2024, 1, 8, 10)) is True
    assert CALENDAR.is_in_session("rb2510.SHFE", cst(2024, 1, 8, 3)) is False


def test_expected_bar_count_sums_day_and_night_windows_excluding_auctions() -> None:
    """R3.11:竞价区间不计入,否则每天的质量检查会凭空报出十分钟缺口。"""
    with_night = CALENDAR.expected_bar_count("rb2510.SHFE", date(2024, 1, 8))
    assert with_night == DAY_MINUTES + NIGHT_MINUTES

    without_night = SUSPENDED_CALENDAR.expected_bar_count("rb2510.SHFE", date(2024, 1, 8))
    assert without_night == DAY_MINUTES


def test_expected_bar_count_is_zero_on_a_non_trading_day() -> None:
    """休市是确定的事实(0 根),与数据缺失(抛错)不同。"""
    assert CALENDAR.expected_bar_count("rb2510.SHFE", date(2024, 1, 6)) == 0


def test_call_auctions_returns_every_auction_window() -> None:
    """夜盘与日盘各有一段竞价,合成单值会丢掉其中一段。"""
    windows = CALENDAR.call_auctions(SHFE, "rb", date(2024, 1, 8))
    assert len(windows) == 2
    assert all(window.kind is SessionKind.CALL_AUCTION for window in windows)


def test_sessions_for_returns_the_effective_definition() -> None:
    spec = CALENDAR.sessions_for(SHFE, "rb", date(2024, 1, 8))
    assert (spec.exchange, spec.product) == (SHFE, "RB")
    assert spec.covers(date(2024, 1, 8))
    assert len(spec.day_windows) == 3


def test_table_store_satisfies_the_reference_data_port() -> None:
    """替身必须真的实现端口。mypy 不检查 tests,这条是唯一的拦截点。"""
    assert isinstance(STORE, ReferenceDataStore)


def test_calendar_has_no_dependence_on_the_system_clock() -> None:
    """R3.14:本日历没有"取当前时间"的入口,全部判定由入参决定。

    真正的强制手段是全局那条「只有 `core/timeutil.py` 可读系统时钟」的 AST 守卫
    (见 tests/test_architecture_contract.py),此处断言其可观测后果。
    """
    moment = cst(2024, 1, 8, 21, 30)
    expected = CALENDAR.to_trading_day(moment, SHFE, "rb")
    assert all(CALENDAR.to_trading_day(moment, SHFE, "rb") == expected for _ in range(3))
