import importlib
from dataclasses import replace
from decimal import Decimal as D

import pytest
from research_helpers import pivot_config_data

from qf.pivot_stop import EntryPlan
from qf.research_config import validate_research_config
from qf.trade_risk import ContractSpec


def api():
    return importlib.import_module('qf.continuous_risk')


def spec(tick=1):
    return ContractSpec('SHFE.rb2505', D(tick), D(10), 1, 1, D(3000), D(2), 'fixture')


def risk():
    return validate_research_config(pivot_config_data()).risk


def held(side=1, **changes):
    state = api().LogicalRisk(trade_id='logical-1', side=side, quantity=1,
        entry_price=D(4000), initial_r=D(1000), sealed=True, stage=2,
        floor_gross=D(500), peak_gross=D(2200), realized_gross=D(1800),
        first_offset_amount=D(10), last_fill_ns=10)
    return replace(state, **changes)


def fill(*, side=1, volume=1, price=4000, closing=False, time_ns=20):
    return dict(symbol='SHFE.rb2505', direction=('SELL' if side == 1 else 'BUY')
                if closing else ('BUY' if side == 1 else 'SELL'),
                offset='CLOSE' if closing else 'OPEN', volume=volume,
                price=price, time_ns=time_ns)


@pytest.mark.parametrize('side,stop', [(1, '3870'), (-1, '4130')])
def test_roll_preserves_r_and_floor_long_and_short(side, stop):
    state = held(side)
    assert api().logical_stop(state, spec=spec()) == D(stop)
    assert api().logical_gross(state, price=D(stop), spec=spec()) == 500


@pytest.mark.parametrize('side,entry,stop', [(1, '4001', '3873'), (-1, '4000', '4128')])
def test_tick_rounding_never_weakens_money_floor(side, entry, stop):
    state = held(side, entry_price=D(entry))
    result = api().logical_stop(state, spec=spec(3))
    assert result == D(stop)
    assert api().logical_gross(state, price=result, spec=spec(3)) >= 500


@pytest.mark.parametrize('side', [1, -1])
def test_partial_roll_out_and_in_keep_one_trade(side):
    state = held(side, quantity=2, realized_gross=D(0), floor_gross=D(-1000),
                 stage=0, peak_gross=D(0))
    state = api().apply_logical_fill(state,
        fill(side=side, price=4000+side*90, closing=True), role='roll_out',
        spec=spec(), entry_plan=None, risk=risk())
    assert state.quantity == 1 and state.realized_gross == 900
    assert api().logical_gross(state, price=D(4000+side*90), spec=spec()) == 1800
    state = api().apply_logical_fill(state,
        fill(side=side, price=4000+side*90, closing=True, time_ns=21), role='roll_out',
        spec=spec(), entry_plan=None, risk=risk())
    assert state.quantity == 0 and state.realized_gross == 1800
    assert state.trade_id == 'logical-1' and state.initial_r == 1000
    old_peak, old_stage, old_floor = state.peak_gross, state.stage, state.floor_gross
    state = api().apply_logical_fill(state, fill(side=side, price=4500, time_ns=22),
        role='roll_in', spec=spec(), entry_plan=None, risk=risk())
    assert state.quantity == 1 and state.entry_price == 4500
    assert (state.peak_gross, state.stage, state.floor_gross) == (old_peak, old_stage, old_floor)
    assert state.initial_r == 1000 and state.trade_id == 'logical-1'
    assert api().logical_gross(state, price=D(4500), spec=spec()) == 1800


def test_initial_r_uses_actual_fills_until_sealed():
    plan = EntryPlan(1, 2, D(4000), D(3950), None, D(50), D(500), D(1000), D(6000), 'ready')
    state = api().LogicalRisk(trade_id='first')
    state = api().apply_logical_fill(state, fill(price=4001), role='strategy_open',
        spec=spec(), entry_plan=plan, risk=risk())
    assert state.initial_r == 510 and state.floor_gross == -510
    state = api().apply_logical_fill(state, fill(price=4003, time_ns=21), role='strategy_open',
        spec=spec(), entry_plan=plan, risk=risk())
    assert state.entry_price == 4002 and state.initial_r == 1040
    state = api().seal_logical(state)
    assert state.sealed and state.first_offset_amount == 20
    with pytest.raises(ValueError):
        api().apply_logical_fill(state, fill(), role='strategy_open',
            spec=spec(), entry_plan=plan, risk=risk())


def test_stairs_use_cumulative_profit_and_never_move_back():
    state = held(quantity=1, stage=0, floor_gross=D(-1000), peak_gross=D(0),
                 realized_gross=D(900))
    state = api().protect_logical(state, price=D(4010), time_ns=20, risk=risk(), spec=spec())
    assert state.stage == 1 and state.floor_gross == 10
    state = api().protect_logical(state, price=D(4110), time_ns=21, risk=risk(), spec=spec())
    assert state.stage == 2 and state.floor_gross == 500 and state.peak_gross == 2000
    retrace = api().protect_logical(state, price=D(4000), time_ns=22, risk=risk(), spec=spec())
    assert retrace.floor_gross == 500 and retrace.stage == 2 and retrace.exit_reason is None
    stale = api().protect_logical(retrace, price=D(1), time_ns=19, risk=risk(), spec=spec())
    assert stale == retrace


@pytest.mark.parametrize('gross,reason', [(3000, 'take_profit'), (500, 'stair_stop'),
                                       (-1200, 'stair_stop')])
def test_flat_during_roll_still_checks_terminal_money(gross, reason):
    state = held(quantity=0, realized_gross=D(gross))
    state = api().protect_logical(state, price=D(4000), time_ns=20, risk=risk(), spec=spec())
    assert state.exit_reason == reason
    assert api().logical_stop(state, spec=spec()) is None


def test_fixed_amount_exit_and_disabled_stairs():
    rules = replace(risk(), take_profit_mode='amount', take_profit_value=D(2500),
                    stairs_enabled=False)
    state = held(stage=0, floor_gross=D(-1000), peak_gross=D(0), realized_gross=D(1800))
    assert api().protect_logical(state, price=D(4069), time_ns=20,
        risk=rules, spec=spec()).exit_reason is None
    assert api().protect_logical(state, price=D(4070), time_ns=20,
        risk=rules, spec=spec()).exit_reason == 'take_profit'


@pytest.mark.parametrize('changes', [dict(volume=True), dict(volume=0), dict(price=0),
    dict(time_ns=0), dict(symbol='SHFE.cu2505'), dict(direction='UNKNOWN')])
def test_invalid_fill_does_not_change_risk(changes):
    with pytest.raises(ValueError):
        api().apply_logical_fill(held(quantity=0), fill() | changes, role='roll_in',
            spec=spec(), entry_plan=None, risk=risk())
