"""合约代码规范化 —— 全系统唯一的写法转换点(R27.2)。

**Canonical_Symbol 是系统内部唯一的合约表示形式**:品种代码 + 4 位年月 +
交易所后缀,例如 `rb2510.SHFE`(R27.1)。

为什么值得单列一个模块:同一个东西有多种写法,是这类系统最大的静默 bug 源。
这三类错误的共同特征是**不报错、结果还更好看** ——

- `MA509` 到底是 2015 年 9 月还是 2025 年 9 月(R27.3)
- 品种代码大小写不一致导致同一合约被当成两个(R27.7)
- 连续合约标识误入报单(R28.10)

规范形式加边缘转换是唯一可靠的防法:内部一律用 Canonical_Symbol,与外部接口的
转换**只在本模块发生**,其他模块不得包含合约代码的字符串拼接与截取(R27.2)。

**年月与大小写的判断规则本身是市场事实,不是实现选择**:郑商所 3 位年月码的推断、
各交易所的品种大小写惯例、组合代码形式,其表驱动测试的预期值须由开发者依据交易所
合约细则核对填入(R34.4)。本模块只提供结构与纯逻辑,不声称这些规则已被验证。
"""

from __future__ import annotations

import re
from datetime import date

from core import Exchange, SymbolAmbiguous

__all__ = [
    "is_combination",
    "is_continuous",
    "split_canonical",
    "to_canonical",
    "to_wire",
]

#: 连续合约标识的固定中缀:`rb.MAIN@oi_prev:back`。换月规则与复权方式编进标识本身,
#: 因为同一品种在不同规则与复权方式下是**不同的价格序列**(B5),存储路径同样按此分层。
#:
#: 刻意不导出:其他模块若要判断连续标识应调用 `is_continuous()`,导出中缀会诱发
#: 各处的字符串拼接,而 R27.2 要求拼接与截取只出现在本模块。
_CONTINUOUS_INFIX = ".MAIN@"

#: 品种代码使用大写惯例的交易所。**这是市场事实,须依据交易所合约细则核对**:
#: 郑商所与中金所的合约代码为大写(MA、TA、IF),上期所、能源中心、大商所、
#: 广期所为小写(rb、sc、i、si)。猜错的表现是同一合约被存成两个代码。
_UPPERCASE_PRODUCT_EXCHANGES = frozenset({Exchange.CZCE, Exchange.CFFEX})

#: 组合与跨期套利代码的前导标识(R27.8)。**须依据各交易所文档核对**:
#: 上期所与大商所用 SP/SPC,郑商所用 SPD/IPS。这类代码的价格是价差而非价格。
#: 核对后修正本常量即可,调用方不必改动。
_COMBINATION_LEADERS = ("SPD", "SPC", "SP", "IPS")

#: 外部接口标识。
_CTP_API = "ctp"

#: 3 位年月码的世纪推断半径。±10 年足以覆盖"挂牌到交割"的合理跨度,
#: 且使候选年份恰好落在同一个十年周期内两到三个。
_CENTURY_SPAN_YEARS = 10

_BODY_PATTERN = re.compile(r"^(?P<product>[A-Za-z]+)(?P<digits>\d{3,4})$")


def _split_off_exchange(text: str) -> tuple[str, Exchange | None]:
    """拆出 `(代码主体, 交易所后缀)`;无后缀时返回 None。"""
    if "." not in text:
        return text, None
    body, _, suffix = text.rpartition(".")
    try:
        return body, Exchange(suffix.upper())
    except ValueError as exc:
        legal = [item.value for item in Exchange]
        raise ValueError(f"未知的交易所后缀 {suffix!r};合法取值为 {legal}") from exc


def _normalize_product(product: str, exchange: Exchange) -> str:
    """按交易所惯例归一品种大小写(R27.7)。"""
    if exchange in _UPPERCASE_PRODUCT_EXCHANGES:
        return product.upper()
    return product.lower()


def _check_month(digits: str) -> int:
    """取出并校验年月码末两位的月份。

    不校验的后果:`rb2513` 会成为"合法"的规范形式,下游按它查费率、建分区都不报错,
    只是永远查不到数据。
    """
    month = int(digits[-2:])
    if not 1 <= month <= 12:
        raise ValueError(f"月份越界:{digits!r} 解析出第 {month} 月")
    return month


def _resolve_year_month(digits: str, asof: date, exchange: Exchange) -> int:
    """把 3 位或 4 位年月码解析为 4 位 YYMM 整数。

    4 位码是本世纪内的 YYMM,无歧义。3 位码(`509`)只用于郑商所,必须靠参考日期
    定世纪:取与 asof 距离最近的候选年份(R27.3),**距离并列时报错而非任选**
    (R27.5)—— 猜错时数据仍能对上,属典型静默错配。
    """
    month = _check_month(digits)
    if len(digits) == 4:
        return int(digits)
    if exchange is not Exchange.CZCE:
        raise ValueError(
            f"{exchange.value} 不使用 3 位年月码({digits!r});该形式仅郑商所有(R27.3)"
        )
    year_digit = int(digits[0])
    candidates = [
        year
        for year in range(
            asof.year - _CENTURY_SPAN_YEARS,
            asof.year + _CENTURY_SPAN_YEARS + 1,
        )
        if year % 10 == year_digit
    ]
    if not candidates:
        raise SymbolAmbiguous(f"参考日期 {asof} 附近没有年份以 {year_digit} 结尾的合约")
    ranked = sorted((abs((date(year, month, 1) - asof).days), year) for year in candidates)
    if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
        raise SymbolAmbiguous(
            f"{digits!r} 在参考日期 {asof} 下不唯一:"
            f"{ranked[0][1]} 年与 {ranked[1][1]} 年与该日期的距离相同。"
            f"请给出更接近合约存续期的参考日期,或改用具交易所后缀的 4 位年月写法"
        )
    return (ranked[0][1] % 100) * 100 + month


def to_canonical(raw: str, exchange: Exchange, asof: date) -> str:
    """将外部写法转换为 Canonical_Symbol。

    Args:
        raw: 外部写法,例如 CTP 返回的 `MA509` 或 `rb2510`;也接受已带后缀的
            `rb2510.SHFE`(此时后缀须与 `exchange` 一致)。
        exchange: 该合约所属交易所。大小写惯例按交易所而定(R27.7)。
        asof: 参考日期。**郑商所 3 位年月码必须有它才能定世纪**(R27.3)。

    Returns:
        Canonical_Symbol,例如 `MA2509.CZCE`。

    Raises:
        SymbolAmbiguous: 3 位年月码在给定参考日期下对应多个候选(R27.5)。
        ValueError: 空串、无法解析、后缀与入参冲突、非郑商所用 3 位码,
            或输入是连续/组合合约标识(R27.8/R28.10)。

    已知局限:合约挂牌与到期日期构成的有效区间校验(R27.4)需要合约表,随 Phase 4
    落地;当前只做语法解析与世纪推断。该缺口由 `tools/requirements_coverage.py`
    如实报出,不在本阶段假装已覆盖。
    """
    text = raw.strip()
    if not text:
        raise ValueError("合约代码不得为空")
    if is_continuous(text):
        raise ValueError(f"{raw!r} 是连续合约标识,不是可交易合约;绝不可用于报单(R28.10)")
    if is_combination(text):
        raise ValueError(f"{raw!r} 是组合/跨期合约代码,不得转换为普通合约(R27.8)")

    body, suffix = _split_off_exchange(text)
    if suffix is not None and suffix is not exchange:
        raise ValueError(
            f"{raw!r} 的后缀 {suffix.value} 与入参交易所 {exchange.value} 不一致;"
            f"二者必须一致,否则同一合约会有两个规范形式"
        )
    if is_continuous(body) or is_combination(body):
        raise ValueError(f"{raw!r} 去掉后缀后仍是连续或组合标识,不可转换(R27.8)")

    match = _BODY_PATTERN.match(body)
    if match is None:
        raise ValueError(
            f"无法解析合约代码 {raw!r};期望 <品种代码><年月>,例如 rb2510 或 MA509"
        )
    product = _normalize_product(match.group("product"), exchange)
    yymm = _resolve_year_month(match.group("digits"), asof, exchange)
    return f"{product}{yymm:04d}.{exchange.value}"


def to_wire(canonical: str, api: str) -> str:
    """将 Canonical_Symbol 转换为指定外部接口要求的写法(R27.6)。

    Args:
        canonical: 例如 `MA2509.CZCE`。
        api: 目标接口标识,目前支持 `"ctp"`。

    Returns:
        该接口要求的写法。CTP 对郑商所要求 3 位年月,故 `MA2509.CZCE` → `MA509`;
        其余交易所去掉后缀即为其写法,`rb2510.SHFE` → `rb2510`。

    Raises:
        ValueError: canonical 为连续合约标识 —— **连续序列只是信号输入,
            绝不可用于报单**(R28.10);或 api 未知。

    与 `to_canonical` 构成往返:对任何合法 Canonical_Symbol,转为接口写法再在
    同一十年内转回须得到原值(R27.9)。
    """
    if is_continuous(canonical):
        raise ValueError(
            f"{canonical!r} 是连续合约标识;连续序列只是信号输入,绝不可用于报单(R28.10)"
        )
    product, yymm, exchange = split_canonical(canonical)
    if api != _CTP_API:
        raise ValueError(f"未知的外部接口 {api!r};目前仅支持 {_CTP_API!r}")
    if exchange is Exchange.CZCE:
        return f"{product}{int(yymm) % 1000:03d}"
    return f"{product}{yymm}"


def split_canonical(canonical: str) -> tuple[str, str, Exchange]:
    """拆出 `(品种代码, 4 位年月, 交易所)`。

    提供此函数的目的是让其他模块**不必自己切字符串** —— R27.2 要求合约代码的
    拼接与截取只出现在本模块内。需要品种代码去查费率或时段时调用它,
    不要写 `symbol[:2]`。

    Raises:
        ValueError: 输入不是合法 Canonical_Symbol —— 缺后缀、年月不是 4 位、
            品种大小写不符合该交易所惯例(R27.7),或是连续/组合标识。
    """
    if is_continuous(canonical):
        raise ValueError(f"{canonical!r} 是连续合约标识,没有单一合约要素可拆(R28.7)")
    text = canonical.strip()
    body, suffix = _split_off_exchange(text)
    if suffix is None:
        raise ValueError(
            f"{canonical!r} 缺少交易所后缀;Canonical_Symbol 必须形如 rb2510.SHFE(R27.1)"
        )
    if is_combination(body):
        raise ValueError(f"{canonical!r} 是组合/跨期合约代码,不是单一合约(R27.8)")
    match = _BODY_PATTERN.match(body)
    if match is None:
        raise ValueError(f"无法解析合约代码主体 {body!r}")
    digits = match.group("digits")
    if len(digits) != 4:
        raise ValueError(
            f"{canonical!r} 的年月是 {len(digits)} 位;"
            f"Canonical_Symbol 一律使用 4 位年月,3 位只出现在外部接口写法中(R27.1)"
        )
    _check_month(digits)
    product = match.group("product")
    normalized = _normalize_product(product, suffix)
    if normalized != product:
        raise ValueError(
            f"{canonical!r} 的品种代码大小写不符合 {suffix.value} 惯例,"
            f"应为 {normalized}(R27.7)"
        )
    return product, digits, suffix


def is_combination(raw: str) -> bool:
    """判定是否为组合合约或跨期套利合约代码(R27.8)。

    这类代码必须被识别并**排除**出订阅清单(R2.6)与 Bar 构建 —— 它们的价格是
    价差而非价格,混进单合约序列会污染指标与回测。

    已知局限:各交易所的组合代码形式(上期所 SP/SPC、大商所 SP/SPC、
    郑商所 SPD/IPS)来自文档而非实测,须依据交易所文档核对后再定稿。核对后
    修正 `_COMBINATION_LEADERS` 即可,调用方不必改动。
    """
    token = raw.strip().upper()
    if "&" in token:
        return True
    # 前导标识必须以空格与腿分隔。不能只看"前导后面跟非字母":上期所纸浆的品种代码
    # 就是 sp,`sp2509` 按那条规则会被误判为组合,一个真实合约就此无法订阅。
    leader, separator, _ = token.partition(" ")
    return bool(separator) and leader in _COMBINATION_LEADERS


def is_continuous(symbol: str) -> bool:
    """判定是否为连续合约标识。

    纯字符串判定,无领域知识 —— 它是 R28.10 那条「绝不对连续合约报单」的守卫
    在 `execution/` 与 `gateway/` 的调用前提。
    """
    return _CONTINUOUS_INFIX in symbol
