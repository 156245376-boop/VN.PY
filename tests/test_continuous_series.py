import importlib
from decimal import Decimal as D

import pytest

from qf import ma_cross
from qf.pivot_stop import latest_confirmed_pivot

BASE = 1_700_000_000_000_000_000
MINUTE = 60_000_000_000
OLD, NEW = 'SHFE.rb2405', 'SHFE.rb2410'


def row(i, value, **changes):
    return dict(datetime=BASE+i*MINUTE, end_ns=BASE+(i+1)*MINUTE,
                open=value, high=value+1, low=value-1, close=value,
                volume=20, close_oi=100, completed=True) | changes


def series():
    cls = importlib.import_module('qf.continuous_series').SignalSeries
    value = cls(60, max_window=202)
    value.switch(old_symbol=None, new_symbol=OLD, detected_ns=BASE, old_rows=[], new_rows=[])
    return value


def test_gap_only_roll_has_no_cross_and_does_not_rewrite_past():
    value = series()
    for i in range(200):
        value.append(symbol=OLD, row=row(i, 100), completed_at_ns=BASE+(i+1)*MINUTE)
    before = value.window()
    evidence = value.switch(old_symbol=OLD, new_symbol=NEW, detected_ns=BASE+200*MINUTE,
        old_rows=[row(199, 100)], new_rows=[row(199, 200)])
    assert evidence['offset'] == 100 and evidence['reference_ns'] == BASE+199*MINUTE
    assert value.window() == before
    for i in range(200, 203):
        bar = value.append(symbol=NEW, row=row(i, 200), completed_at_ns=BASE+(i+1)*MINUTE)
        assert bar['close'] == 100 and bar['raw']['close'] == 200
        assert ma_cross.completed_cross_closed(value.window(), 5, 20,
            completed_ns=BASE+(i+1)*MINUTE, allow_nonpositive=True) is None
    assert len(value.window()) == 202


def test_future_reference_cannot_change_causal_adjustment():
    value = series()
    old_rows, new_rows = [row(0, 100), row(9, 999)], [row(0, 300), row(9, 9999)]
    evidence = value.switch(old_symbol=OLD, new_symbol=NEW, detected_ns=BASE+MINUTE,
        old_rows=old_rows, new_rows=new_rows)
    assert evidence['offset'] == 200
    bar = value.append(symbol=NEW, row=row(1, 190), completed_at_ns=BASE+2*MINUTE)
    assert bar['close'] == D(-10) and bar['raw']['close'] == 190
    assert bar['source_symbol'] == NEW


@pytest.mark.parametrize('future_close', [float('nan'), 0])
def test_unavailable_future_prices_do_not_affect_reference(future_close):
    value = series()
    evidence = value.switch(old_symbol=OLD, new_symbol=NEW, detected_ns=BASE+MINUTE,
        old_rows=[row(0, 100), row(9, 100) | {'close': future_close}],
        new_rows=[row(0, 200), row(9, 200)])
    assert evidence['offset'] == 100


@pytest.mark.parametrize('old_rows,new_rows', [([], []), ([row(2, 100)], [row(2, 200)]),
    ([row(0, 100)], [row(1, 200)]),
    ([row(0, 100, completed=False)], [row(0, 200)])])
def test_future_and_misaligned_reference_are_rejected(old_rows, new_rows):
    value = series()
    with pytest.raises(ValueError):
        value.switch(old_symbol=OLD, new_symbol=NEW, detected_ns=BASE+MINUTE,
                     old_rows=old_rows, new_rows=new_rows)
    assert value.symbol == OLD and value.offset == 0


def test_boundary_incomplete_and_duplicate_rows_are_not_mixed():
    value = series()
    value.append(symbol=OLD, row=row(0, 100), completed_at_ns=BASE+MINUTE)
    value.switch(old_symbol=OLD, new_symbol=NEW, detected_ns=BASE+MINUTE+100,
        old_rows=[row(0, 100)], new_rows=[row(0, 200)])
    assert value.append(symbol=NEW, row=row(1, 200),
                        completed_at_ns=BASE+2*MINUTE) is None
    assert value.take_discards()[0]['reason'] == 'roll_boundary_incomplete'
    assert not value.take_discards()
    bar = row(2, 201)
    assert value.append(symbol=NEW, row=bar, completed_at_ns=BASE+3*MINUTE)['close'] == 101
    assert value.append(symbol=NEW, row=bar, completed_at_ns=BASE+3*MINUTE) is None
    with pytest.raises(ValueError):
        value.append(symbol=NEW, row=bar | {'close': 200}, completed_at_ns=BASE+3*MINUTE)
    with pytest.raises(ValueError):
        value.append(symbol=NEW, row=row(3, 201), completed_at_ns=BASE+3*MINUTE)


@pytest.mark.parametrize('changes', [dict(close=0), dict(high=1), dict(low=999),
                                    dict(close=float('nan'))])
def test_raw_bad_prices_remain_invalid(changes):
    value = series()
    with pytest.raises(ValueError):
        value.append(symbol=OLD, row=row(0, 100) | changes, completed_at_ns=BASE+MINUTE)


def test_nonpositive_closed_signals_work_without_loosening_raw_entry_checks():
    rows = [row(i, v) for i, v in enumerate([-7, -8, -9, -8, -7])]
    signal = ma_cross.completed_cross_closed(rows, 2, 3,
        completed_ns=BASE+5*MINUTE, allow_nonpositive=True)
    assert signal.direction == 1 and signal.bar_start_ns == BASE+4*MINUTE
    assert ma_cross.completed_cross_closed(rows, 2, 3, completed_ns=BASE+5*MINUTE) is None
    with pytest.raises(ValueError):
        latest_confirmed_pivot(rows, side=1, left=2, right=2, as_of_ns=BASE+5*MINUTE)
    pivot = latest_confirmed_pivot(rows, side=1, left=2, right=2,
        as_of_ns=BASE+5*MINUTE, allow_nonpositive=True)
    assert pivot.price == -10 and pivot.bar_start_ns == BASE+2*MINUTE
