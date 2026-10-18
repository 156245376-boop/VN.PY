from dataclasses import replace
from decimal import Decimal as D

import pytest
from research_helpers import config_data

from qf.research_config import validate_research_config
from qf.trade_risk import (
    ContractSpec,
    apply_entry_fill,
    empty_risk,
    protect,
    seal_entry,
    size_order,
)


def inputs():
    return (validate_research_config(config_data()).risk,
            ContractSpec('SHFE.rb2505', D(1), D(10), 1, 1, D(3000), D(2), 'SDK模拟'))


def entered(side=1, *, price='1000', quantity=2, risk=None, spec=None):
    default_risk, default_spec = inputs()
    return apply_entry_fill(empty_risk(), side=side, price=D(price), quantity=quantity,
                            time_ns=10, risk=risk or default_risk, spec=spec or default_spec,
                            trade_id='position-1')


def test_risk_budget_rounds_down_and_respects_capital_minimum_and_margin():
    risk, spec = inputs()
    risk = replace(risk, stop_ticks=30)
    result = size_order(risk, spec, available=D(100000), startup_equity=D(100000))
    assert (result.lots, result.initial_r) == (3, D(900))
    assert size_order(risk, spec, available=D(2500), startup_equity=D(100000)).lots == 0
    assert size_order(replace(risk, risk_budget=D(299)), spec,
                      available=D(100000), startup_equity=D(100000)).lots == 0
    assert size_order(replace(risk, risk_budget=D(500)), replace(spec, min_open_lots=2),
                      available=D(100000), startup_equity=D(100000)).lots == 0
    assert size_order(risk, spec, available=D(1000000), startup_equity=D(6000)).lots == 1


@pytest.mark.parametrize('side,prices,stops', [(1, [1050, 1100, 1150], [1001, 1025]),
                                             (-1, [950, 900, 850], [999, 975])])
def test_long_short_staircases_exact_thresholds(side, prices, stops):
    risk, spec = inputs()
    state = seal_entry(entered(side))
    assert state.initial_r == 1000
    for i in range(2):
        state = protect(state, price=D(prices[i]), time_ns=20+i, risk=risk, spec=spec)
        assert state.stop_price == stops[i]
    state = protect(state, price=D(prices[2]), time_ns=22, risk=risk, spec=spec)
    assert state.exit_reason == 'take_profit'
    assert state.initial_r == 1000


def test_gap_rounding_stale_quote_and_same_time_quote():
    risk, spec = inputs()
    state = protect(entered(), price=D(1100), time_ns=20, risk=risk, spec=spec)
    assert state.stop_price == 1025
    assert protect(state, price=D(1000), time_ns=19, risk=risk, spec=spec) == state
    state = protect(state, price=D(1025), time_ns=20, risk=risk, spec=spec)
    assert state.exit_reason == 'stair_stop'
    state = protect(entered(), price=D(1200), time_ns=20, risk=risk, spec=spec)
    assert state.exit_reason == 'take_profit'
    odd = replace(risk, stop_ticks=51)
    for side, price, want in [(1, 1102, 1025), (-1, 898, 975)]:
        state = protect(entered(side, risk=odd), price=D(price), time_ns=20,
                        risk=odd, spec=spec)
        assert state.stop_price == want


def test_partial_fill_does_not_relax_stop_or_change_sealed_r():
    risk, spec = inputs()
    state = protect(entered(quantity=1), price=D(1050), time_ns=20, risk=risk, spec=spec)
    newer = apply_entry_fill(state, side=1, price=D(950), quantity=1, time_ns=21,
                             risk=risk, spec=spec, trade_id='position-1')
    assert newer.stop_price >= state.stop_price
    assert newer.quantity == 2
    assert protect(newer, price=D(2000), time_ns=20, risk=risk, spec=spec) == newer
    with pytest.raises(ValueError):
        apply_entry_fill(seal_entry(newer), side=1, price=D(1000), quantity=1,
                         time_ns=22, risk=risk, spec=spec, trade_id='position-1')


def test_fixed_amount_exit_and_impossible_stair_configuration():
    risk, spec = inputs()
    fixed = replace(risk, take_profit_mode='amount', take_profit_value=D(2500))
    state = protect(entered(risk=fixed), price=D(1125), time_ns=20, risk=fixed, spec=spec)
    assert state.exit_reason == 'take_profit'
    invalid = replace(fixed, take_profit_value=D(500))
    assert size_order(invalid, spec, available=D(100000), startup_equity=D(100000)).lots == 0
