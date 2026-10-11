"""需要系统外部权威资料核对的市场事实(R34.4–R34.7)。

**本文件的用例一律标记 `pending_expected`,当前必然失败,这是刻意的。**
失败不是缺陷,而是把「预期值还没有人工核对」这件事变成可观测的(R34.7)。
`tests/conftest.py` 在用例进入执行前就让它失败,所以跳过或误绿都不可能。

为什么必须这样:由生成实现的同一模型产出预期值,测试就退化为
「模型的理解 == 模型的实现」的同义反复,证明力为零(ADR-0001)。而本项目会亏钱的
缺陷恰好集中在这里 —— 周五夜盘的归属、郑商所 3 位年月的世纪、夜盘收盘时间。
这些代码读起来完全合理,错的是**与现实不符**。

## 开发者要做的事

1. 按下面的清单取得外部资料(交易所年度休市公告、交易细则、合约挂牌公告、CTP 代码规范)
2. 把 `REAL_TRADING_DAYS` / `REAL_SESSION_SPECS` 填成真实数据
3. 核对每个用例的预期值,确认或修正后**删除 `pending_expected` 标记**
4. 若预期值与实现不符,改实现而不是改预期值

## 已知的执行风险(ADR-0001 记录,无技术手段可缓解)

「完全跳过」已由 R34.7 转为可观测,但**「敷衍填入」——照抄实现的当前输出、或直接
向模型索取取值——仍然不可观测,且测试会全部通过。** 填入时必须对照资料原文。
"""

from __future__ import annotations

from datetime import date

import pytest

from core import Exchange, NotInTradingSession
from meta import (
    TradingCalendar,
    TradingDayRecord,
    TradingSessionSpec,
    is_combination,
    to_canonical,
    to_wire,
)
from store_double import TableReferenceDataStore, cst

# ---------------------------------------------------------------------------
# 待填数据。留空即表示尚未核对,下列用例因此全部失败。
# ---------------------------------------------------------------------------

#: 日历覆盖范围。填数据时一并收窄到实际有据可查的区间 ——
#: 覆盖范围之外的查询必须抛 CalendarMissing(R3.13),写宽了会把这个保护废掉。
REAL_COVERAGE: tuple[date, date] = (date(2015, 1, 1), date(2030, 12, 31))

#: 真实交易日历。来源:交易所年度休市安排公告。
#: 注意 `preceded_by_night_session`:节前最后一个交易日为 False(夜盘整体停),
#: 周五为 True(夜盘归属下周一)。
REAL_TRADING_DAYS: tuple[TradingDayRecord, ...] = ()

#: 真实品种时段定义。来源:交易所交易细则及其历次修订公告。
#: 须覆盖夜盘增设与取消、夜盘收盘时间 23:00 / 01:00 / 02:30 的各版本。
REAL_SESSION_SPECS: tuple[TradingSessionSpec, ...] = ()

#: 待填:螺纹钢在一个含夜盘的正常交易日应存在的 1 分钟 Bar 数量。
#: 依据交易所时段公告手算填入,不得取自实现的当前输出。
EXPECTED_RB_BAR_COUNT: int | None = None


def _real_store() -> TableReferenceDataStore:
    return TableReferenceDataStore(
        coverage=REAL_COVERAGE,
        trading_days=REAL_TRADING_DAYS,
        session_specs=REAL_SESSION_SPECS,
    )


# ---------------------------------------------------------------------------
# 交易日归属(R3.5–R3.7)
# ---------------------------------------------------------------------------


@pytest.mark.pending_expected(
    "需交易所 2024 年度休市安排公告:确认 2024-01-05 为交易日、2024-01-08 为其后"
    "第一个交易日,且 2024-01-05 的夜盘未停盘"
)
def test_friday_night_belongs_to_next_monday() -> None:
    """R3.6 + 实施计划 Phase 1 验证清单。"""
    calendar = TradingCalendar(_real_store())
    moment = cst(2024, 1, 5, 21, 30)
    assert calendar.to_trading_day(moment, Exchange.SHFE, "rb") == date(2024, 1, 8)


@pytest.mark.pending_expected(
    "需交易所春节休市安排公告:确认 2024-02-08 是节前最后一个交易日,且其夜盘按公告停盘"
)
def test_night_session_is_absent_before_spring_festival() -> None:
    """R3.7:停盘意味着该时段不存在。错误实现会把它归到节后第一个交易日。"""
    calendar = TradingCalendar(_real_store())
    with pytest.raises(NotInTradingSession):
        calendar.to_trading_day(cst(2024, 2, 8, 21, 0), Exchange.SHFE, "rb")


@pytest.mark.pending_expected(
    "需上期所交易细则:确认螺纹钢日盘与夜盘的时段划分,及夜盘收盘时间(23:00 / 01:00 / 02:30)"
)
def test_expected_bar_count_matches_exchange_sessions() -> None:
    """R3.11:应有 Bar 数是质量检查的分母,算错会让缺口表整体失真。"""
    calendar = TradingCalendar(_real_store())
    assert calendar.expected_bar_count("rb2510.SHFE", date(2024, 1, 8)) == EXPECTED_RB_BAR_COUNT


# ---------------------------------------------------------------------------
# 合约代码规范化(R27.3/R27.6/R27.7/R27.8)
# ---------------------------------------------------------------------------


@pytest.mark.pending_expected(
    "需郑商所合约挂牌公告:确认 MA509 在 2025 年语境下指 2025 年 9 月交割的甲醇合约"
)
def test_czce_three_digit_code_resolves_in_2025() -> None:
    """R27.3 + 实施计划 Phase 1 验证清单。"""
    assert to_canonical("MA509", Exchange.CZCE, date(2025, 6, 1)) == "MA2509.CZCE"


@pytest.mark.pending_expected(
    "需郑商所合约挂牌公告:确认 MA509 在 2015 年语境下指 2015 年 9 月交割的甲醇合约"
)
def test_czce_three_digit_code_resolves_in_2015() -> None:
    """同一位 3 位码在两个年代指向不同合约 —— 这正是静默错配的来源。"""
    assert to_canonical("MA509", Exchange.CZCE, date(2015, 6, 1)) == "MA1509.CZCE"


@pytest.mark.pending_expected(
    "需 CTP 合约代码规范:确认郑商所在报单接口使用 3 位年月,其余交易所为品种+4 位年月"
)
def test_ctp_wire_format() -> None:
    """R27.6 + 实施计划 Phase 1 验证清单。"""
    assert to_wire("MA2509.CZCE", "ctp") == "MA509"
    assert to_wire("rb2510.SHFE", "ctp") == "rb2510"


@pytest.mark.pending_expected(
    "需各交易所合约细则:确认上期所/大商所/能源中心/广期所品种代码小写,郑商所/中金所大写"
)
def test_exchange_product_case_conventions() -> None:
    """R27.7:猜错的表现是同一合约被存成两个代码,数据仍然"对得上"。"""
    asof = date(2025, 6, 1)
    assert to_canonical("RB2510", Exchange.SHFE, asof) == "rb2510.SHFE"
    assert to_canonical("i2501", Exchange.DCE, asof) == "i2501.DCE"
    assert to_canonical("ma2509", Exchange.CZCE, asof) == "MA2509.CZCE"
    assert to_canonical("if2509", Exchange.CFFEX, asof) == "IF2509.CFFEX"


@pytest.mark.pending_expected(
    "需各交易所组合与跨期套利代码文档:确认上期所/大商所 SP、SPC 与郑商所 SPD、IPS 的实际形式"
)
def test_combination_code_forms_are_recognized() -> None:
    """R27.8:组合代码的价格是价差,混进单合约序列会污染指标与回测。"""
    for code in (
        "SP rb2510&rb2601",
        "SPC rb2510&rb2601",
        "SPD MA509&MA601",
        "IPS MA509&MA601",
    ):
        assert is_combination(code), f"{code} 应被识别为组合/套利代码"
