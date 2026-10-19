"""定仓与阶梯保护的纯计算；金额为毛价差，成交反馈另行核实。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING

from qf.research_config import decimal_value

if TYPE_CHECKING:
    from qf.pivot_stop import EntryPlan

ZERO = Decimal(0)


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    price_tick: Decimal
    volume_multiple: Decimal
    min_open_lots: int
    lot_step: int
    margin_per_lot: Decimal
    commission_per_lot: Decimal
    cost_source: str

    def __post_init__(self):
        for field in ('price_tick', 'volume_multiple', 'margin_per_lot', 'commission_per_lot'):
            value = decimal_value(getattr(self, field))
            if value < 0 or (field != 'commission_per_lot' and not value):
                raise ValueError('合约规格或成本缺失')
            object.__setattr__(self, field, value)
        if (type(self.min_open_lots) is not int or self.min_open_lots < 1
                or type(self.lot_step) is not int or self.lot_step < 1 or not self.cost_source):
            raise ValueError('最小手数或成本来源缺失')


@dataclass(frozen=True)
class SizingDecision:
    lots: int
    budget: Decimal
    initial_r: Decimal
    margin: Decimal
    reason: str


def size_order(risk, spec, *, available, startup_equity):
    available, startup_equity = decimal_value(available), decimal_value(startup_equity)
    per_lot = spec.price_tick * spec.volume_multiple * risk.stop_ticks
    lots = (int(risk.risk_budget // per_lot) if risk.sizing == 'risk_budget' else risk.fixed_lots)
    capital = max(ZERO, min(available, startup_equity * risk.max_margin_ratio))
    affordable = int(capital // spec.margin_per_lot)
    if risk.sizing == 'fixed' and (lots > affordable or lots > risk.max_lots):
        return SizingDecision(0, risk.risk_budget, ZERO, ZERO, 'fixed_size_unaffordable')
    lots = min(lots, risk.max_lots, affordable)
    lots -= lots % spec.lot_step
    if lots < spec.min_open_lots:
        return SizingDecision(0, risk.risk_budget, ZERO, ZERO, 'below_minimum_size')
    initial_r = per_lot * lots
    endpoint = (initial_r * risk.take_profit_value if risk.take_profit_mode == 'r_multiple'
                else risk.take_profit_value)
    if risk.stairs_enabled and (endpoint <= initial_r * risk.second_trigger_r
                               or risk.first_offset_ticks >= risk.stop_ticks*risk.first_trigger_r):
        return SizingDecision(0, risk.risk_budget, ZERO, ZERO, 'stairs_unreachable')
    return SizingDecision(lots, risk.risk_budget, initial_r, spec.margin_per_lot * lots, 'ready')


@dataclass(frozen=True)
class RiskState:
    trade_id: str = ''
    side: int = 0
    quantity: int = 0
    entry_price: Decimal = ZERO
    initial_r: Decimal = ZERO
    sealed: bool = False
    stage: int = 0
    stop_price: Decimal = ZERO
    peak_gross: Decimal = ZERO
    last_quote_ns: int = 0
    last_fill_ns: int = 0
    exit_reason: str | None = None


def empty_risk():
    return RiskState()


def _tighten(old, new, side):
    return max(old, new) if side > 0 else min(old, new)


def _tick_price(price, tick, side):
    return (price / tick).to_integral_value(
        rounding=ROUND_FLOOR if side > 0 else ROUND_CEILING) * tick


def apply_entry_fill(state, *, side, price, quantity, time_ns, risk, spec, trade_id,
                     entry_plan: EntryPlan | None = None):
    price = decimal_value(price)
    if (state.sealed or type(side) is not int or side not in (-1, 1)
            or type(quantity) is not int or quantity <= 0 or price <= 0
            or type(time_ns) is not int or time_ns <= 0
            or (state.quantity and (state.side != side or state.trade_id != trade_id))):
        raise ValueError('入场成交与持仓状态不一致')
    total = state.quantity + quantity
    average = (state.entry_price*state.quantity + price*quantity) / total
    if entry_plan is None:
        if not hasattr(risk, 'stop_ticks'):
            raise ValueError('缺少冻结入场计划')
        distance = spec.price_tick*risk.stop_ticks
        stop = average - side*distance
        initial_r = total*distance*spec.volume_multiple
        invalid = False
    else:
        if (entry_plan.side != side or entry_plan.stop_price is None or entry_plan.lots < 1):
            raise ValueError('入场计划与成交不一致')
        stop = entry_plan.stop_price
        initial_r = total*abs(average-stop)*spec.volume_multiple
        invalid = (price-stop)*side <= 0 or total > entry_plan.lots
    if state.quantity:
        stop = _tighten(state.stop_price, stop, side)
    reason = state.exit_reason
    if entry_plan is not None and reason is None:
        if invalid:
            reason = 'entry_stop_invalid'
        elif (state.stage and time_ns >= state.last_quote_ns
              and (price-state.stop_price)*side <= 0):
            reason = 'stair_stop'
    return replace(state, trade_id=trade_id, side=side, quantity=total, entry_price=average,
                   initial_r=initial_r, stop_price=stop,
                   exit_reason=reason,
                   last_fill_ns=max(time_ns, state.last_fill_ns))


def seal_entry(state):
    return replace(state, sealed=True)


def close_trade_fills(state, fills):
    for fill in fills:
        if (fill['offset'] not in ('CLOSE', 'CLOSETODAY')
                or fill['direction'] != ('SELL' if state.side == 1 else 'BUY')
                or type(fill['volume']) is not int or not 0 < fill['volume'] <= state.quantity):
            raise ValueError('平仓成交与实际持仓不一致')
        state = replace(state, quantity=state.quantity-fill['volume'],
                        last_fill_ns=max(state.last_fill_ns, int(fill['time_ns'])))
    return state


def protect(state, *, price, time_ns, risk, spec):
    price = decimal_value(price)
    if type(time_ns) is not int or price <= 0:
        raise ValueError('报价无效')
    if (not state.quantity or state.exit_reason
            or time_ns < max(state.last_quote_ns, state.last_fill_ns)):
        return state
    gross = (price-state.entry_price)*state.side*state.quantity*spec.volume_multiple
    peak = max(state.peak_gross, gross)
    state = replace(state, peak_gross=peak, last_quote_ns=time_ns)
    if (price-state.stop_price)*state.side <= 0:
        return replace(state, exit_reason='stair_stop' if state.stage else 'initial_stop')
    endpoint = (state.initial_r*risk.take_profit_value if risk.take_profit_mode == 'r_multiple'
                else risk.take_profit_value)
    if gross >= endpoint:
        return replace(state, exit_reason='take_profit')
    if not risk.stairs_enabled:
        return state
    stop, stage = state.stop_price, state.stage
    if peak >= state.initial_r*risk.first_trigger_r:
        stop = _tighten(stop, _tick_price(state.entry_price + state.side*
                        risk.first_offset_ticks*spec.price_tick, spec.price_tick, state.side),
                        state.side)
        stage = max(stage, 1)
    if peak >= state.initial_r*risk.second_trigger_r:
        lock = state.initial_r*risk.second_lock_r / (state.quantity*spec.volume_multiple)
        stop = _tighten(stop, _tick_price(state.entry_price+state.side*lock,
                                        spec.price_tick, state.side), state.side)
        stage = max(stage, 2)
    return replace(state, stop_price=stop, stage=stage,
                   exit_reason='stair_stop' if (price-stop)*state.side <= 0 else None)
