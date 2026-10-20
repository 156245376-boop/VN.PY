from dataclasses import replace
from decimal import Decimal

import pandas as pd
from test_continuous_config import continuous_data
from test_continuous_risk import spec

from qf.local_backtest import LocalBacktestEngine
from qf.local_data import LocalFrame
from qf.research_config import validate_research_config
from qf.trade_risk import ContractSpec

MINUTE = 60_000_000_000
OLD = 'SHFE.rb2505'
NEW = 'SHFE.rb2510'


def config():
    raw = continuous_data()
    raw.update(
        bar_seconds=60,
        fast_period=2,
        slow_period=3,
        start='1970-01-01',
        end='1970-01-02',
        initial_balance='100000',
    )
    raw['risk'].update(
        sizing='risk_budget',
        fixed_lots=1,
        risk_budget=Decimal('1000'),
        pivot_left=1,
        pivot_right=1,
        stairs_enabled=True,
        first_trigger_r=Decimal('1'),
        first_offset_ticks=1,
        second_trigger_r=Decimal('2'),
        second_lock_r=Decimal('0.5'),
        take_profit_mode='r_multiple',
        take_profit_value=Decimal('3'),
        limit_lots=False,
        limit_margin=False,
        max_lots=None,
        max_margin_ratio=None,
    )
    return validate_research_config(raw)


def row(
    stamp,
    open_,
    high,
    low,
    close,
    *,
    symbol=OLD,
    offset=0,
):
    return {
        'symbol': symbol,
        'duration': 60,
        'time_ns': stamp,
        'open': open_-offset,
        'high': high-offset,
        'low': low-offset,
        'close': close-offset,
        'actual_open': open_,
        'actual_high': high,
        'actual_low': low,
        'actual_close': close,
        'offset': offset,
        'volume': 10,
        'close_oi': 20,
        'completed': True,
        'completed_ns': stamp + MINUTE,
    }


def dataset(
    *,
    exit_open=96,
    entry_high=104,
    entry_low=100,
    include_exit=True,
):
    values = [
        row(100, 100, 101, 99, 100),
        row(200, 99, 100, 98, 99),
        row(300, 98, 99, 97, 98),
        row(400, 101, 102, 100, 101),
        row(500, 103, entry_high, entry_low, 103),
    ]
    if include_exit:
        values.append(row(600, exit_open, exit_open + 1, exit_open - 1, exit_open))
    return LocalFrame(
        dataset_id='fixture',
        frame=pd.DataFrame(values),
        symbols=(OLD,),
        specs={OLD: spec()},
        bar_seconds=60,
        precision='minute',
        continuous='KQ.m@SHFE.rb',
        coverage_complete=True,
    )


def roll_dataset(new_spec=None):
    values = [
        row(100, 100, 101, 99, 100),
        row(200, 99, 100, 98, 99),
        row(300, 98, 99, 97, 98),
        row(400, 101, 102, 100, 101),
        row(500, 103, 104, 102, 103),
        row(600, 204, 206, 203, 205, symbol=NEW, offset=100),
        row(700, 198, 200, 197, 200, symbol=NEW, offset=100),
    ]
    new_spec = new_spec or ContractSpec(
        NEW,
        Decimal('1'),
        Decimal('10'),
        1,
        1,
        Decimal('3000'),
        Decimal('2'),
        'fixture',
    )
    return LocalFrame(
        dataset_id='roll-fixture',
        frame=pd.DataFrame(values),
        symbols=(OLD, NEW),
        specs={OLD: spec(), NEW: new_spec},
        bar_seconds=60,
        precision='minute',
        continuous='KQ.m@SHFE.rb',
        coverage_complete=True,
    )


def test_long_signal_opens_next_executable_bar_and_applies_fee():
    result = LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'backtest_finished'
    assert result.engine_kind == 'local_research'
    assert len(result.signals) == 2
    assert result.signals[0]['bar_index'] == 3
    assert result.fills[0]['role'] == 'strategy_open'
    assert result.fills[0]['signal_bar'] == 3
    assert result.fills[0]['execution_bar'] == 4
    assert result.fills[0]['direction'] == 'BUY'
    assert result.fills[0]['price'] == '103'
    assert result.fills[0]['fee'] == '32'
    assert result.fills[1]['role'] == 'strategy_close'
    assert result.fills[1]['price'] == '96'
    assert result.closed_trade_count == 1
    assert result.trades[0]['quantity'] == 16
    assert result.fees == Decimal('64')
    assert result.gross_pnl == Decimal('-1120')
    assert result.final_equity == Decimal('98816')
    assert result.trades[0]['exit_reason'] == 'initial_stop'


def test_same_bar_stop_and_target_use_conservative_stop_first():
    result = LocalBacktestEngine().run(
        dataset(exit_open=103, entry_high=140, entry_low=90),
        config(),
        progress=None,
        cancel=lambda: False,
    )
    first_trade_fills = [
        fill for fill in result.fills if fill['direction'] == 'SELL'
    ]
    assert first_trade_fills[0]['execution_bar'] == 4
    assert first_trade_fills[0]['price'] == '97'
    assert (
        first_trade_fills[0]['intrabar_resolution']
        == 'conservative_stop_first'
    )
    assert result.trades[0]['exit_reason'] == 'initial_stop'


def test_cancel_stops_before_further_bars_are_processed():
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) >= 2

    result = LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=cancel
    )
    assert result.status == 'stopped' and result.reason == 'requested_stop'
    assert result.fills == []


def test_fingerprint_is_stable_for_the_same_inputs():
    first = LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=lambda: False
    )
    second = LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=lambda: False
    )
    assert first.fingerprint() == second.fingerprint()
    assert first.profile['elapsed_seconds'] >= 0


def test_roll_closes_old_reopens_new_and_preserves_one_logical_trade():
    result = LocalBacktestEngine().run(
        roll_dataset(), config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'backtest_finished'
    roles = [fill['role'] for fill in result.fills]
    assert roles == ['strategy_open', 'roll_out', 'roll_in', 'strategy_close']
    assert [fill['symbol'] for fill in result.fills] == [OLD, OLD, NEW, NEW]
    assert result.fills[2]['price'] == '204'
    assert result.trades[0]['first_symbol'] == OLD
    assert result.trades[0]['last_symbol'] == NEW
    assert result.trades[0]['initial_stop'] == '97'
    assert result.trades[0]['final_stop'] == '198'
    assert result.trades[0]['fill_count'] == 4
    assert result.trades[0]['gross_pnl'] == '-960'
    assert result.closed_trade_count == 1
    assert len(result.rolls) == 1


def test_incompatible_roll_spec_fails_without_silent_size_change():
    incompatible = ContractSpec(
        NEW,
        Decimal('1'),
        Decimal('20'),
        1,
        1,
        Decimal('3000'),
        Decimal('2'),
        'fixture',
    )
    result = LocalBacktestEngine().run(
        roll_dataset(incompatible), config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'failed'
    assert result.reason == 'roll_spec_incompatible'
    assert [fill['role'] for fill in result.fills] == ['strategy_open']


def test_reverse_signal_closes_then_opens_opposite_direction(monkeypatch):
    values = [
        row(100, 100, 101, 90, 100),
        row(200, 99, 100, 80, 99),
        row(300, 100, 102, 97, 101),
        row(400, 100, 105, 99, 104),
        row(500, 103, 104, 98, 101),
        row(600, 100, 102, 99, 101),
        row(700, 102, 103, 100, 102),
    ]

    def signals(*_args, **_kwargs):
        return [
            {
                'bar_index': 2,
                'time_ns': '300',
                'completed_ns': str(300 + MINUTE),
                'direction': 1,
                'close': 101.0,
                'symbol': OLD,
            },
            {
                'bar_index': 4,
                'time_ns': '500',
                'completed_ns': str(500 + MINUTE),
                'direction': -1,
                'close': 101.0,
                'symbol': OLD,
            },
        ]

    monkeypatch.setattr('qf.local_backtest.ma_cross_signals', signals)
    fixture = replace(dataset(include_exit=False), frame=pd.DataFrame(values))
    result = LocalBacktestEngine().run(
        fixture, config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'backtest_finished'
    assert [fill['direction'] for fill in result.fills[:3]] == [
        'BUY',
        'SELL',
        'SELL',
    ]
    assert [fill['execution_bar'] for fill in result.fills[:3]] == [3, 5, 5]
    assert result.trades[0]['status'] == 'closed'
    assert result.trades[0]['exit_reason'] == 'ma_reverse'
    assert result.trades[1]['status'] == 'open'
    assert result.open_position == -20


def test_insufficient_risk_budget_is_rejected_visibly():
    raw = config().public()
    raw['risk']['risk_budget'] = '1'
    tiny = validate_research_config(raw)
    result = LocalBacktestEngine().run(
        dataset(), tiny, progress=None, cancel=lambda: False
    )
    assert result.status == 'backtest_finished'
    assert result.fills == []
    assert result.entry_rejections[0]['reason'] == 'below_minimum_size'
    assert result.final_equity == Decimal('100000')


def test_partial_entry_uses_actual_fill_quantity_for_r_and_fees():
    result = LocalBacktestEngine(fill_fraction=Decimal('0.5')).run(
        dataset(), config(), progress=None, cancel=lambda: False
    )
    assert result.fills[0]['volume'] == 8
    assert result.fills[0]['requested_volume'] == 16
    assert result.fills[0]['fee'] == '16'
    assert result.trades[0]['quantity'] == 8
    assert result.fees == Decimal('32')
    assert result.final_equity == Decimal('99408')


def test_incomplete_coverage_and_tick_precision_fail_before_execution():
    incomplete = replace(dataset(), coverage_complete=False)
    result = LocalBacktestEngine().run(
        incomplete, config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'failed'
    assert result.reason == 'coverage_incomplete'
    assert result.fills == []

    tick = replace(dataset(), precision='tick')
    result = LocalBacktestEngine().run(
        tick, config(), progress=None, cancel=lambda: False
    )
    assert result.status == 'failed'
    assert result.reason == 'tick_path_not_available'
    assert result.fills == []
