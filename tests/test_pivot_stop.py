from dataclasses import replace
from decimal import Decimal as D
from importlib import import_module

import pytest
from research_helpers import pivot_config_data
from test_trade_risk import inputs

from qf.research_config import validate_research_config
from qf.trade_risk import apply_entry_fill, close_trade_fills, empty_risk, protect, seal_entry


def rows(values):
    return [dict(datetime=(i + 1) * 60_000_000_000, end_ns=(i + 2) * 60_000_000_000,
                 open=v, close=v, high=v, low=v, completed=True)
            for i, v in enumerate(values)]


def pivot_module():
    return import_module('qf.pivot_stop')


def test_pivot_requires_completed_right_bars():
    p = pivot_module()
    bars = rows([9, 8, 5, 7, 8])
    assert p.latest_confirmed_pivot(bars, side=1, left=2, right=2,
                                     as_of_ns=300_000_000_000) is None
    found = p.latest_confirmed_pivot(bars, side=1, left=2, right=2,
                                     as_of_ns=360_000_000_000)
    assert (found.kind, found.price, found.bar_start_ns, found.confirmed_ns) == (
        'low', D(5), 180_000_000_000, 360_000_000_000)
    bars[-1]['completed'] = False
    assert p.latest_confirmed_pivot(bars, side=1, left=2, right=2,
                                     as_of_ns=360_000_000_000) is None


def test_peak_plateau_future_mutation_and_rolling_prefixes():
    p = pivot_module()
    bars = rows([1, 2, 5, 3, 2, 9, 10, 8, 7])
    last = None
    for count in range(1, len(bars) + 1):
        prefix = bars[:count]
        last = p.latest_confirmed_pivot(prefix, side=-1, left=2, right=2,
                                        as_of_ns=prefix[-1]['end_ns'], previous=last)
        assert last == p.latest_confirmed_pivot(bars, side=-1, left=2, right=2,
                                                as_of_ns=prefix[-1]['end_ns'])
    assert last.price == 10
    previous = p.latest_confirmed_pivot(bars, side=-1, left=2, right=2,
                                        as_of_ns=360_000_000_000)
    bars[-1]['high'] = 999999
    assert p.latest_confirmed_pivot(bars, side=-1, left=2, right=2,
                                     as_of_ns=360_000_000_000) == previous
    assert p.latest_confirmed_pivot([], side=-1, left=2, right=2,
                                     as_of_ns=720_000_000_000, previous=previous) == previous
    assert p.latest_confirmed_pivot([], side=-1, left=2, right=2,
                                     as_of_ns=100, previous=previous) is None
    assert p.latest_confirmed_pivot(rows([1, 2, 5, 5, 2]), side=-1, left=2, right=2,
                                     as_of_ns=360_000_000_000) is None


def entry(*, side=1, stop='995', reference='1000', risk=None, spec=None, available='100000'):
    p = pivot_module()
    cfg = risk or validate_research_config(pivot_config_data()).risk
    spec = spec or inputs()[1]
    pivot = None if stop is None else p.Pivot('low' if side == 1 else 'high', D(stop), 1, 2, 2, 2)
    return p.plan_pivot_entry(cfg, spec, side=side, reference_price=D(reference), pivot=pivot,
                              available=D(available), startup_equity=D(100000))


def test_position_scales_with_stop_distance_and_optional_caps():
    risk = validate_research_config(pivot_config_data()).risk
    assert entry().lots == 20
    assert entry(stop='990').lots == 10
    assert entry(side=-1, stop='1005').lots == 20
    capped = entry(risk=replace(risk, limit_lots=True, max_lots=5))
    assert capped.lots == 5 and capped.reason == 'max_lots_limited'
    assert entry(risk=replace(risk, max_lots=1)).lots == 20
    assert entry(risk=replace(risk, limit_margin=True, max_margin_ratio=D('.1'))).lots == 3
    assert entry(available='6000').lots == 2
    assert entry(available='2500').lots == 0
    assert entry(risk=replace(risk, risk_budget=D(49))).lots == 0
    assert entry(spec=replace(inputs()[1], min_open_lots=25)).lots == 0
    assert entry(risk=replace(risk, sizing='fixed', fixed_lots=3), available='6000').lots == 0


@pytest.mark.parametrize('stop,reason', [(None, 'pivot_missing'), ('1001', 'stop_wrong_side'),
                                       ('999.5', 'stop_off_tick')])
def test_invalid_stop_never_guesses_an_older_pivot(stop, reason):
    plan = entry(stop=stop)
    assert plan.lots == 0 and plan.reason == reason


def test_fills_keep_frozen_stop_and_seal_actual_r():
    risk = validate_research_config(pivot_config_data()).risk
    spec = inputs()[1]
    plan = entry()
    state = apply_entry_fill(empty_risk(), side=1, price=D(1001), quantity=10,
                             time_ns=10, risk=risk, spec=spec, trade_id='t', entry_plan=plan)
    assert (state.stop_price, state.initial_r) == (995, 600)
    state = apply_entry_fill(state, side=1, price=D(1001), quantity=10,
                             time_ns=11, risk=risk, spec=spec, trade_id='t', entry_plan=plan)
    state = seal_entry(state)
    assert state.stop_price == 995 and state.initial_r == 1200
    state = protect(state, price=D(1007), time_ns=12, risk=risk, spec=spec)
    assert state.stop_price == 1002 and state.stage == 1
    state = protect(state, price=D(1013), time_ns=13, risk=risk, spec=spec)
    assert state.stop_price == 1004 and state.stage == 2
    state = close_trade_fills(state, [dict(direction='SELL', offset='CLOSE', volume=10,
                                          time_ns=14)])
    assert state.initial_r == 1200 and state.quantity == 10


def test_bad_entry_price_is_retained_for_exit_and_tier_touch_exits():
    risk = validate_research_config(pivot_config_data()).risk
    spec = inputs()[1]
    state = apply_entry_fill(empty_risk(), side=1, price=D(994), quantity=1,
                             time_ns=10, risk=risk, spec=spec, trade_id='t', entry_plan=entry())
    assert state.quantity == 1 and state.exit_reason == 'entry_stop_invalid'
    plan = entry(stop='999')
    assert plan.lots > 0
    state = apply_entry_fill(empty_risk(), side=1, price=D(1000), quantity=1,
                             time_ns=10, risk=risk, spec=spec, trade_id='u', entry_plan=plan)
    state = protect(seal_entry(state), price=D(1001), time_ns=11, risk=risk, spec=spec)
    assert state.exit_reason == 'stair_stop' and state.stop_price == 1001


def test_partial_fill_keeps_original_anchor_and_respects_advanced_protection():
    risk = validate_research_config(pivot_config_data()).risk
    spec, plan = inputs()[1], entry()
    state = apply_entry_fill(empty_risk(), side=1, price=D(1000), quantity=10,
                             time_ns=10, risk=risk, spec=spec, trade_id='t', entry_plan=plan)
    state = protect(state, price=D(1005), time_ns=11, risk=risk, spec=spec)
    assert state.stop_price == 1001
    updated = apply_entry_fill(state, side=1, price=D(1000), quantity=10,
                               time_ns=12, risk=risk, spec=spec, trade_id='t', entry_plan=plan)
    assert updated.initial_r == 1000 and updated.stop_price == 1001
    assert updated.exit_reason == 'stair_stop'
