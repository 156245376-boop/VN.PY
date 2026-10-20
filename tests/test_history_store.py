from datetime import date

import pytest

from qf.data_catalog import CoverageReport, DataCapability, DataRequest
from qf.history_store import HistoryStore


def request(**changes):
    values = dict(
        continuous='KQ.m@SHFE.rb', symbol='SHFE.rb2505', bar_seconds=60,
        start=date(2025, 1, 2), end=date(2025, 1, 3), precision='minute')
    values.update(changes)
    return DataRequest(**values)


def capability():
    return DataCapability(
        status='available', reason='fixture', minute_available=True,
        tick_available=False, source='fixture')


def bar(stamp, close, **changes):
    value = {
        'symbol': 'SHFE.rb2505', 'duration': 60, 'time_ns': stamp,
        'open': close, 'high': close+1, 'low': close-1, 'close': close,
        'volume': 10, 'close_oi': 20, 'completed': True,
    }
    value.update(changes)
    return value


def test_bars_are_deduplicated_and_group_read_is_ordered(tmp_path):
    store = HistoryStore(tmp_path)
    dataset = store.create_dataset(request(), 'fixture', capability())
    assert dataset == store.create_dataset(request(), 'fixture', capability())
    assert store.write_bars(dataset, [bar(100, 10), bar(160, 12), bar(100, 10)]) == 2
    frame = store.load_bars(dataset, symbol='SHFE.rb2505')
    assert frame.time_ns.tolist() == [100, 160]
    assert frame.close.tolist() == [10.0, 12.0]
    assert frame.completed.tolist() == [1, 1]


def test_duplicate_conflict_rolls_back_whole_batch(tmp_path):
    store = HistoryStore(tmp_path)
    dataset = store.create_dataset(request(), 'fixture', capability())
    store.write_bars(dataset, [bar(100, 10)])
    with pytest.raises(ValueError):
        store.write_bars(dataset, [bar(160, 12), bar(100, 11)])
    assert store.load_bars(dataset).time_ns.tolist() == [100]


def test_mapping_instruments_and_coverage_are_persisted(tmp_path):
    store = HistoryStore(tmp_path)
    dataset = store.create_dataset(request(), 'fixture', capability())
    store.write_instruments(dataset, [{
        'symbol': 'SHFE.rb2505', 'price_tick': '1', 'volume_multiple': '10',
        'margin_per_lot': '3000', 'commission_per_lot': '2'}])
    store.write_mapping(dataset, [{
        'time_ns': 100, 'old_symbol': None, 'new_symbol': 'SHFE.rb2505',
        'offset': '0', 'reference_ns': None}])
    report = CoverageReport(
        expected_days=[date(2025, 1, 2), date(2025, 1, 3)],
        observed_days=[date(2025, 1, 2), date(2025, 1, 3)], issues=[])
    store.write_coverage(dataset, report)
    assert store.coverage(dataset).complete()
    assert store.load_instruments(dataset)[0]['volume_multiple'] == '10'
    assert store.load_mapping(dataset)[0]['new_symbol'] == 'SHFE.rb2505'


def test_invalid_rows_and_unknown_dataset_are_rejected(tmp_path):
    store = HistoryStore(tmp_path)
    with pytest.raises(ValueError):
        store.create_dataset(request(continuous='bad'), 'fixture', capability())
    dataset = store.create_dataset(request(), 'fixture', capability())
    for bad in (
        bar(100, 10, high=9),
        bar(100, 0),
        bar(100, 10, volume=-1),
        bar(100, 10, completed=1),
        bar(100, 10, symbol='private'),
    ):
        with pytest.raises(ValueError):
            store.write_bars(dataset, [bad])
