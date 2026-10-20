from datetime import date

from qf.data_acquisition import (
    AcquiredData,
    DataCancelled,
    DataPermissionError,
    prepare_dataset,
)
from qf.data_catalog import DataCapability, DataRequest
from qf.history_store import HistoryStore


def request():
    return DataRequest(
        continuous='KQ.m@SHFE.rb', symbol='SHFE.rb2505', bar_seconds=60,
        start=date(2025, 1, 2), end=date(2025, 1, 3), precision='minute')


def capability(status='available', reason='fixture'):
    return DataCapability(
        status=status, reason=reason, minute_available=status == 'available',
        tick_available=False, source='fixture')


class DeniedProvider:
    def probe(self, _request):
        return capability('permission_required', '需要tq_dl权限')

    def download(self, *_args, **_kwargs):
        raise AssertionError('denied download must not start')


class CancelProvider:
    def probe(self, _request):
        return capability()

    def download(self, _request, _temp_dir, _progress, cancel):
        assert cancel() is True
        raise DataCancelled()


class SuccessProvider:
    def probe(self, _request):
        return capability()

    def download(self, _request, _temp_dir, progress, cancel):
        progress('download', percent=50)
        assert cancel() is False
        progress('validate', percent=100)
        return AcquiredData(
            bars=[{
                'symbol': 'SHFE.rb2505', 'duration': 60, 'time_ns': 1735780440000000000,
                'open': 3300, 'high': 3310, 'low': 3290, 'close': 3305,
                'volume': 100, 'close_oi': 200, 'completed': True}],
            instruments=[{
                'symbol': 'SHFE.rb2505', 'price_tick': '1', 'volume_multiple': '10',
                'margin_per_lot': '3000', 'commission_per_lot': '2'}],
            mapping=[{
                'time_ns': 1735780440000000000, 'old_symbol': None,
                'new_symbol': 'SHFE.rb2505', 'offset': '0', 'reference_ns': None}],
            expected_days=[date(2025, 1, 2)],
            observed_days=[date(2025, 1, 2)],
            issues=[])


def test_permission_denied_does_not_create_complete_dataset(tmp_path):
    result = prepare_dataset(
        DeniedProvider(), HistoryStore(tmp_path), request(),
        progress=lambda *_a, **_k: None, cancel=lambda: False)
    assert result['status'] == 'permission_required'
    assert result['dataset_id'] is None
    assert 'tq_dl' in result['reason']
    assert list(tmp_path.glob('*/journal.sqlite3')) == []


def test_cancel_keeps_dataset_incomplete(tmp_path):
    store = HistoryStore(tmp_path)
    result = prepare_dataset(
        CancelProvider(), store, request(),
        progress=lambda *_a, **_k: None, cancel=lambda: True)
    assert result['status'] == 'cancelled'
    assert result['dataset_id']
    with store.connect() as db:
        assert db.execute('SELECT status FROM data_sets').fetchone()[0] == 'cancelled'


def test_success_writes_only_after_all_normalized_data(tmp_path):
    store = HistoryStore(tmp_path)
    stages = []
    result = prepare_dataset(
        SuccessProvider(), store, request(), progress=lambda stage, **fields:
        stages.append((stage, fields)), cancel=lambda: False)
    assert result['status'] == 'ready'
    dataset = result['dataset_id']
    assert store.coverage(dataset).complete()
    assert len(store.load_bars(dataset)) == 1
    assert store.load_instruments(dataset)[0]['volume_multiple'] == '10'
    assert stages == [('download', {'percent': 50}), ('validate', {'percent': 100})]


def test_explicit_download_permission_error_is_sanitized(tmp_path):
    class Provider(SuccessProvider):
        def download(self, *_args, **_kwargs):
            raise DataPermissionError('需要tq_dl权限')

    result = prepare_dataset(
        Provider(), HistoryStore(tmp_path), request(),
        progress=lambda *_a, **_k: None, cancel=lambda: False)
    assert result['status'] == 'permission_required'
    assert result['reason'] == '需要tq_dl权限'
