from datetime import date

import pandas as pd
import pytest

from qf.data_catalog import CoverageReport, DataCapability, DataRequest
from qf.history_store import HistoryStore
from qf.local_data import load_continuous_frame
from qf.local_signals import ma_cross_signals


def frame():
    return pd.DataFrame({
        'symbol': ['SHFE.rb2505']*5,
        'time_ns': [100, 200, 300, 400, 500],
        'open': [100, 99, 98, 101, 103],
        'high': [101, 100, 99, 102, 104],
        'low': [99, 98, 97, 100, 102],
        'close': [100, 99, 98, 101, 103],
        'volume': [10]*5,
        'close_oi': [20]*5,
        'completed': [1, 1, 1, 1, 0],
    })


def test_signal_uses_only_completed_previous_bars():
    signals = ma_cross_signals(frame(), fast=2, slow=3, bar_seconds=60)
    assert len(signals) == 1
    signal = signals[0]
    assert signal['bar_index'] == 3
    assert signal['direction'] == 1
    assert signal['time_ns'] == '400'
    assert signal['completed_ns'] == '60000000400'
    assert signal['fast_current'] == pytest.approx(99.5)
    assert signal['slow_current'] == pytest.approx(99.33333333333333)


def test_forming_bar_and_future_values_cannot_create_signal():
    values = frame()
    first = ma_cross_signals(values, fast=2, slow=3, bar_seconds=60)
    values.loc[4, 'close'] = 1
    values.loc[4, 'open'] = 1
    second = ma_cross_signals(values, fast=2, slow=3, bar_seconds=60)
    assert first == second


def test_prewarm_and_duplicate_or_descending_time_are_rejected():
    values = frame().iloc[:2]
    assert ma_cross_signals(values, fast=2, slow=3, bar_seconds=60) == []
    duplicate = frame()
    duplicate.loc[1, 'time_ns'] = duplicate.loc[0, 'time_ns']
    with pytest.raises(ValueError):
        ma_cross_signals(duplicate, fast=2, slow=3, bar_seconds=60)


def test_loading_applies_mapping_without_rewriting_actual_prices(tmp_path):
    store = HistoryStore(tmp_path)
    request = DataRequest(
        continuous='KQ.m@SHFE.rb', symbol='SHFE.rb2510', bar_seconds=60,
        start=date(2025, 1, 2), end=date(2025, 1, 2), precision='minute')
    capability = DataCapability(
        status='available', reason='fixture', minute_available=True,
        tick_available=False, source='fixture')
    dataset = store.create_dataset(request, 'fixture', capability)
    store.write_bars(dataset, [{
        'symbol': 'SHFE.rb2510', 'duration': 60, 'time_ns': 100,
        'open': 380, 'high': 381, 'low': 379, 'close': 380,
        'volume': 10, 'close_oi': 20, 'completed': True}])
    store.write_instruments(dataset, [{
        'symbol': 'SHFE.rb2510', 'price_tick': '1', 'volume_multiple': '10',
        'margin_per_lot': '3000', 'commission_per_lot': '2',
        'cost_source': 'fixture'}])
    store.write_mapping(dataset, [{
        'time_ns': 10, 'old_symbol': None, 'new_symbol': 'SHFE.rb2510',
        'offset': '100', 'reference_ns': None}])
    store.write_coverage(dataset, CoverageReport(
        expected_days=[date(2025, 1, 2)], observed_days=[date(2025, 1, 2)],
        issues=[]))
    local = load_continuous_frame(store, dataset)
    assert local.frame['actual_close'].tolist() == [380.0]
    assert local.frame['close'].tolist() == [280.0]
    assert local.frame['offset'].tolist() == [100.0]
