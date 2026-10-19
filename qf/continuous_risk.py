"""跨合约逻辑交易的毛金额风险；费用单列，成交反馈由执行层提供。"""

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from qf.research_config import decimal_value as dec

ZERO = Decimal(0)


@dataclass(frozen=True)
class LogicalRisk:
    trade_id: str = ''
    side: int = 0
    quantity: int = 0
    entry_price: Decimal = ZERO
    initial_r: Decimal = ZERO
    sealed: bool = False
    stage: int = 0
    floor_gross: Decimal = ZERO
    peak_gross: Decimal = ZERO
    realized_gross: Decimal = ZERO
    first_offset_amount: Decimal = ZERO
    exit_reason: str | None = None
    last_fill_ns: int = 0
    last_quote_ns: int = 0


def logical_gross(state, *, price, spec):
    price = dec(price)
    if price <= 0:
        raise ValueError('真实报价必须为正')
    return state.realized_gross + state.side * state.quantity * spec.volume_multiple * (
        price - state.entry_price)


def logical_stop(state, *, spec):
    if not state.quantity:
        return None
    if state.side not in (-1, 1) or state.initial_r <= 0:
        raise ValueError('逻辑交易保护状态无效')
    price = state.entry_price + state.side * (state.floor_gross-state.realized_gross) / (
        state.quantity * spec.volume_multiple)
    rounding = ROUND_CEILING if state.side == 1 else ROUND_FLOOR
    return (price/spec.price_tick).to_integral_value(rounding=rounding)*spec.price_tick


def seal_logical(state):
    if not state.trade_id or not state.quantity or state.initial_r <= 0:
        raise ValueError('没有可封存的实际入场')
    return replace(state, sealed=True)


def protect_logical(state, *, price, time_ns, risk, spec):
    if type(time_ns) is not int or time_ns <= 0:
        raise ValueError('报价时间无效')
    if (not state.trade_id or state.exit_reason
            or time_ns < max(state.last_fill_ns, state.last_quote_ns)):
        return state
    gross = logical_gross(state, price=price, spec=spec)
    peak = max(state.peak_gross, gross)
    state = replace(state, peak_gross=peak, last_quote_ns=time_ns)
    endpoint = (state.initial_r*risk.take_profit_value if risk.take_profit_mode == 'r_multiple'
                else risk.take_profit_value)
    stop = logical_stop(state, spec=spec)
    if (gross <= state.floor_gross
            or stop is not None and (dec(price)-stop)*state.side <= 0):
        return replace(state, exit_reason='stair_stop' if state.stage else 'initial_stop')
    if gross >= endpoint:
        return replace(state, exit_reason='take_profit')
    if risk.stairs_enabled:
        floor, stage = state.floor_gross, state.stage
        if peak >= state.initial_r*risk.first_trigger_r:
            floor, stage = max(floor, state.first_offset_amount), max(stage, 1)
        if peak >= state.initial_r*risk.second_trigger_r:
            floor, stage = max(floor, state.initial_r*risk.second_lock_r), max(stage, 2)
        state = replace(state, floor_gross=floor, stage=stage)
        stop = logical_stop(state, spec=spec)
        if gross <= floor or stop is not None and (dec(price)-stop)*state.side <= 0:
            state = replace(state, exit_reason='stair_stop')
    return state


def apply_logical_fill(state, fill, *, role, spec, entry_plan, risk):
    opening = role in ('strategy_open', 'roll_in')
    if role not in ('strategy_open', 'strategy_close', 'roll_out', 'roll_in'):
        raise ValueError('成交用途无效')
    price, quantity, stamp = dec(fill['price']), fill['volume'], fill['time_ns']
    if (not state.trade_id or fill['symbol'] != spec.symbol or price <= 0
            or type(quantity) is not int or quantity < 1
            or type(stamp) is not int or stamp <= 0
            or fill['direction'] not in ('BUY', 'SELL')
            or fill['offset'] not in (('OPEN',) if opening else ('CLOSE', 'CLOSETODAY'))):
        raise ValueError('成交与逻辑交易不一致')
    if opening:
        side = 1 if fill['direction'] == 'BUY' else -1
        if state.side not in (0, side):
            raise ValueError('逻辑交易方向不能因移仓改变')
        if role == 'strategy_open' and (state.sealed or entry_plan is None):
            raise ValueError('初次入场已封存或没有冻结计划')
        if role == 'roll_in' and (not state.sealed or state.initial_r <= 0):
            raise ValueError('移仓必须延续已封存的风险')
        total = state.quantity+quantity
        average = (state.entry_price*state.quantity+price*quantity)/total
        changes = dict(side=side, quantity=total, entry_price=average)
        if role == 'strategy_open':
            if entry_plan.side != side or entry_plan.stop_price is None:
                raise ValueError('冻结止损计划与方向不一致')
            initial_r = total*abs(average-entry_plan.stop_price)*spec.volume_multiple
            invalid = (price-entry_plan.stop_price)*side <= 0 or total > entry_plan.lots
            changes.update(initial_r=initial_r,
                floor_gross=max(state.floor_gross, -initial_r) if state.stage else -initial_r,
                first_offset_amount=total*spec.volume_multiple*spec.price_tick*risk.first_offset_ticks)
            if invalid:
                changes['exit_reason'] = 'entry_stop_invalid'
        return replace(state, **changes, last_fill_ns=max(stamp, state.last_fill_ns))
    if (state.side not in (-1, 1) or quantity > state.quantity
            or fill['direction'] != ('SELL' if state.side == 1 else 'BUY')):
        raise ValueError('平仓成交超过或不匹配实际逻辑持仓')
    realized = (state.realized_gross
                + state.side*quantity*spec.volume_multiple*(price-state.entry_price))
    state = replace(state, quantity=state.quantity-quantity, realized_gross=realized,
                    last_fill_ns=max(stamp, state.last_fill_ns))
    return protect_logical(state, price=price, time_ns=stamp, risk=risk, spec=spec)
