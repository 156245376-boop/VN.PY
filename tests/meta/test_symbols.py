"""合约代码规范化的结构与纯逻辑测试(R27)。

**本文件不声称任何市场事实**:用例的预期值全部由实现内部一致性推出(往返属性、
大小写无关性)、或由构造出的输入直接推得(错误分支)。真实交易所惯例 —— 郑商所
3 位年月的世纪、各交易所品种大小写、组合代码形式 —— 属外部权威资料,由
`tests/meta/test_market_facts.py` 的 `pending_expected` 用例承担(R34.4)。

这个分工是刻意的:若把契约例写成"实现当前的输出",测试就退化为
「模型的理解 == 模型的实现」,证明力为零(ADR-0001)。
"""

from __future__ import annotations

from datetime import date

import pytest

from core import Exchange, SymbolAmbiguous
from meta import is_combination, is_continuous, split_canonical, to_canonical, to_wire

pytestmark = pytest.mark.covers("R27.1", "R27.2", "R27.5", "R27.6", "R27.7", "R27.8", "R27.9")

ASOF = date(2025, 6, 1)

#: 往返测试的样本。这些字符串编码了品种大小写惯例 —— 若惯例判断有误,
#: `split_canonical` 会因大小写校验失败而报错,从而把未核对的假设暴露出来,
#: 而不是让它静默通过。
ROUND_TRIP_SAMPLES = [
    ("rb2510.SHFE", date(2025, 6, 1)),
    ("MA2509.CZCE", date(2025, 6, 1)),
    ("MA1509.CZCE", date(2015, 6, 1)),
    ("i2501.DCE", date(2025, 6, 1)),
    ("sc2511.INE", date(2025, 6, 1)),
    ("IF2509.CFFEX", date(2025, 6, 1)),
    ("si2512.GFEX", date(2025, 6, 1)),
]


@pytest.mark.parametrize(("canonical", "asof"), ROUND_TRIP_SAMPLES)
def test_wire_conversion_round_trips(canonical: str, asof: date) -> None:
    """R27.9:转到接口写法再转回来,须得到原值。"""
    wire = to_wire(canonical, "ctp")
    assert "." not in wire, "接口写法不带交易所后缀"
    assert to_canonical(wire, split_canonical(canonical)[2], asof) == canonical


@pytest.mark.parametrize(("canonical", "asof"), ROUND_TRIP_SAMPLES)
def test_canonical_input_is_accepted_and_idempotent(canonical: str, asof: date) -> None:
    """已带后缀的输入应被接受,且重复转换不再改变其形式(R27.1)。"""
    exchange = split_canonical(canonical)[2]
    assert to_canonical(canonical, exchange, asof) == canonical
    assert to_canonical(to_canonical(canonical, exchange, asof), exchange, asof) == canonical


@pytest.mark.parametrize("exchange", list(Exchange))
def test_product_case_is_normalized_regardless_of_input_case(exchange: Exchange) -> None:
    """R27.7:同一合约的不同大小写输入必须归一到同一个规范形式。

    这里断言的是**幂等与无关性**,不是具体该用哪种大小写 —— 后者是交易所惯例,
    属市场事实。
    """
    lower = to_canonical("rb2510", exchange, ASOF)
    upper = to_canonical("RB2510", exchange, ASOF)
    mixed = to_canonical("rB2510", exchange, ASOF)
    assert lower == upper == mixed


def test_canonical_form_is_product_plus_four_digit_year_month_plus_suffix() -> None:
    result = to_canonical("rb2510", Exchange.SHFE, ASOF)
    body, separator, suffix = result.partition(".")
    assert separator == "." and suffix == "SHFE"
    assert body[-4:].isdigit(), f"年月须为 4 位,实际 {result!r}"


def test_split_canonical_returns_constituents() -> None:
    product, yymm, exchange = split_canonical("rb2510.SHFE")
    assert (product, yymm, exchange) == ("rb", "2510", Exchange.SHFE)


@pytest.mark.parametrize("text", ["", "   ", "rb", "2510", "rb25100", "rb-2510", "rb 2510"])
def test_unparsable_symbol_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match=r"合约代码|无法解析"):
        to_canonical(text, Exchange.SHFE, ASOF)


def test_suffix_conflicting_with_exchange_argument_is_rejected() -> None:
    """带后缀输入的后缀与入参不一致时不得"以其中一个为准":那会让同一合约有两个形式。"""
    with pytest.raises(ValueError, match="不一致"):
        to_canonical("rb2510.DCE", Exchange.SHFE, ASOF)
    with pytest.raises(ValueError, match="未知的交易所后缀"):
        to_canonical("rb2510.NOPE", Exchange.SHFE, ASOF)


def test_three_digit_code_is_rejected_outside_czce() -> None:
    """非郑商所出现 3 位年月码是格式错误,不得当作 4 位码的一部分去猜。"""
    with pytest.raises(ValueError, match="3 位年月码"):
        to_canonical("rb510", Exchange.SHFE, ASOF)


def test_tied_century_candidates_are_ambiguous() -> None:
    """R27.5:两个候选年份与参考日期等距时必须报错,而不是任选一个。

    `MA301` 在 2018-01-01 参考下,2013 与 2023 的 1 月合约距离完全相同。
    """
    with pytest.raises(SymbolAmbiguous, match="不唯一"):
        to_canonical("MA301", Exchange.CZCE, date(2018, 1, 1))


def test_continuous_symbol_is_rejected_everywhere() -> None:
    """R28.10:连续合约标识只是信号输入,绝不可参与报单或当作单一合约。"""
    continuous = "rb.MAIN@oi_prev:back"
    assert is_continuous(continuous)
    with pytest.raises(ValueError, match="连续合约"):
        to_canonical(continuous, Exchange.SHFE, ASOF)
    with pytest.raises(ValueError, match="连续合约"):
        to_wire(continuous, "ctp")
    with pytest.raises(ValueError, match="连续合约"):
        split_canonical(continuous)


def test_combination_symbol_is_not_converted_to_plain_contract() -> None:
    """R27.8:组合/跨期代码的价格是价差而非价格,不得进入单合约序列。"""
    combination = "SP rb2510&rb2601"
    assert is_combination(combination)
    with pytest.raises(ValueError, match="组合"):
        to_canonical(combination, Exchange.SHFE, ASOF)


@pytest.mark.parametrize(
    "text",
    ["rb2510", "MA2509", "i2501", "sp2509", "SP2509", "rb.MAIN@oi_prev:back"],
)
def test_plain_codes_are_not_treated_as_combinations(text: str) -> None:
    """普通合约不得被误判为组合,否则会被排除出订阅清单。

    `sp2509` 是回归用例:品种代码恰好以组合前导 SP 开头,早期实现据"前导后跟
    非字母"判定,把它误判为组合。组合代码的前导必须以空格与腿分隔。
    """
    assert not is_combination(text)


def test_product_whose_code_starts_like_a_combination_leader_converts() -> None:
    assert to_canonical("sp2509", Exchange.SHFE, ASOF) == "sp2509.SHFE"


@pytest.mark.parametrize("text", ["rb2513", "rb2500", "MA513", "MA500"])
def test_month_out_of_range_is_rejected(text: str) -> None:
    """月份越界必须报错,否则会产出一个永远查不到数据的"合法"规范形式。"""
    exchange = Exchange.CZCE if text.startswith("MA") else Exchange.SHFE
    with pytest.raises(ValueError, match="月份越界"):
        to_canonical(text, exchange, ASOF)


def test_split_canonical_rejects_month_out_of_range() -> None:
    with pytest.raises(ValueError, match="月份越界"):
        split_canonical("rb2513.SHFE")


@pytest.mark.parametrize(
    "text",
    ["rb2510", "rb2510.SHFE", "", "MA2509.CZCE"],
)
def test_plain_codes_are_not_treated_as_continuous(text: str) -> None:
    assert not is_continuous(text)


def test_split_canonical_requires_canonical_form() -> None:
    """R27.1:规范形式是唯一的内部表示,不接受外部写法。"""
    with pytest.raises(ValueError, match="缺少交易所后缀"):
        split_canonical("rb2510")
    with pytest.raises(ValueError, match="4 位年月"):
        split_canonical("rb510.SHFE")
    with pytest.raises(ValueError, match="大小写"):
        split_canonical("RB2510.SHFE")
    with pytest.raises(ValueError, match="大小写"):
        split_canonical("ma2509.CZCE")


def test_unknown_wire_api_is_rejected() -> None:
    """未知接口必须报错而非返回一个看起来合理的字符串。"""
    with pytest.raises(ValueError, match="未知的外部接口"):
        to_wire("rb2510.SHFE", "some_other_api")


def test_conversion_is_deterministic() -> None:
    """同一入参重复转换结果相同 —— 否则回测不可复现(R12.16 的前提)。"""
    first = to_canonical("MA509", Exchange.CZCE, ASOF)
    assert all(to_canonical("MA509", Exchange.CZCE, ASOF) == first for _ in range(5))
