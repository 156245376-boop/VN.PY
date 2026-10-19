"""已确认拐点与冻结入场计划；只使用截至指定时刻已完成的柱。"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from qf.research_config import PivotRiskConfig, decimal_value
from qf.trade_risk import ContractSpec

ZERO = Decimal(0)


def normalize_sdk_price(value, tick):
    """只吸收几个浮点ULP的尾差；真正不在刻度上的价格仍保留以便拒绝。"""
    price = decimal_value(value)
    nearest = (price/tick).to_integral_value(rounding=ROUND_HALF_UP)*tick
    tolerance = min(tick*Decimal('1e-8'), Decimal(str(math.ulp(float(price))))*4)
    return nearest if abs(price-nearest) <= tolerance else price


@dataclass(frozen=True)
class Pivot:
    kind: str
    price: Decimal
    bar_start_ns: int
    confirmed_ns: int
    left: int
    right: int


@dataclass(frozen=True)
class EntryPlan:
    side: int
    lots: int
    reference_price: Decimal
    stop_price: Decimal | None
    pivot: Pivot | None
    distance_ticks: Decimal | None
    per_lot_risk: Decimal | None
    planned_r: Decimal
    margin: Decimal
    reason: str


def latest_confirmed_pivot(rows, *, side, left, right, as_of_ns, previous=None,
                           allow_nonpositive=False):
    if (type(side) is not int or side not in (-1, 1) or type(as_of_ns) is not int
            or as_of_ns <= 0 or type(allow_nonpositive) is not bool
            or any(type(n) is not int or not 1 <= n <= 50
                                    for n in (left, right))):
        raise ValueError('拐点参数无效')
    kind, field = ('low', 'low') if side == 1 else ('high', 'high')
    latest = previous if (previous is not None and previous.kind == kind
                          and previous.confirmed_ns <= as_of_ns
                          and previous.left == left and previous.right == right) else None
    closed = []
    for row in rows:
        start, end = int(row['datetime']), int(row['end_ns'])
        if start <= 0 or end <= start:
            raise ValueError('拐点柱时间无效')
        if end <= as_of_ns and row.get('completed', True) is True:
            if closed and start <= closed[-1][0]:
                raise ValueError('拐点柱时间乱序')
            price = decimal_value(row[field])
            if price <= 0 and not allow_nonpositive:
                raise ValueError('拐点价格无效')
            closed.append((start, end, price))
    for i in range(left, len(closed) - right):
        stamp, _, price = closed[i]
        neighbors = closed[i-left:i] + closed[i+1:i+right+1]
        qualifies = all(price < r[2] if side == 1 else price > r[2] for r in neighbors)
        if qualifies and (latest is None or stamp > latest.bar_start_ns):
            latest = Pivot(kind, price, stamp, closed[i+right][1], left, right)
    return latest


def plan_pivot_entry(risk: PivotRiskConfig, spec: ContractSpec, *, side,
                     reference_price, pivot, available, startup_equity):
    reference = normalize_sdk_price(reference_price, spec.price_tick)
    available, startup = decimal_value(available), decimal_value(startup_equity)
    if type(side) is not int or side not in (-1, 1) or reference <= 0 or startup <= 0:
        raise ValueError('入场参考或账户权益无效')
    stop = normalize_sdk_price(pivot.price, spec.price_tick) if pivot else None
    distance = abs(reference-stop) if stop is not None else None
    per_lot = distance * spec.volume_multiple if distance is not None else None

    def decision(lots, reason):
        return EntryPlan(side, lots, reference, stop, pivot,
                         distance/spec.price_tick if distance is not None else None,
                         per_lot, per_lot*lots if per_lot is not None else ZERO,
                         spec.margin_per_lot*lots, reason)

    if pivot is None:
        return decision(0, 'pivot_missing')
    if pivot.kind != ('low' if side == 1 else 'high') or (reference-stop)*side <= 0:
        return decision(0, 'stop_wrong_side')
    if stop % spec.price_tick or reference % spec.price_tick:
        return decision(0, 'stop_off_tick')
    if distance < spec.price_tick:
        return decision(0, 'stop_too_close')
    if (risk.stairs_enabled and risk.first_offset_ticks*spec.price_tick
            > distance*risk.first_trigger_r):
        return decision(0, 'stairs_unreachable')
    desired = int(risk.risk_budget // per_lot) if risk.sizing == 'risk_budget' else risk.fixed_lots
    funds = max(ZERO, available)
    if risk.limit_margin:
        funds = min(funds, startup*risk.max_margin_ratio)
    affordable = int(funds // spec.margin_per_lot)
    maximum = risk.max_lots if risk.limit_lots else desired
    if risk.sizing == 'fixed' and (desired > maximum or desired > affordable):
        return decision(0, 'fixed_size_unaffordable')
    lots = min(desired, maximum, affordable)
    lots -= lots % spec.lot_step
    if lots < spec.min_open_lots:
        return decision(0, 'below_minimum_size')
    if (risk.stairs_enabled and risk.take_profit_mode == 'amount'
            and risk.take_profit_value <= per_lot*lots*risk.second_trigger_r):
        return decision(0, 'stairs_unreachable')
    reason = ('max_lots_limited' if lots < desired and lots == maximum else
              'margin_ratio_limited' if lots < desired and risk.limit_margin
              and funds < max(ZERO, available) else
              'available_funds_limited' if lots < desired else 'ready')
    return decision(lots, reason)
