from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from qf.data_acquisition import (
    AcquiredData,
    DataCancelled,
    DataPermissionError,
    DataUnavailableError,
    TqSdkDownloadProvider,
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


class DownloaderApi:
    def __init__(self, *, expired=False, missing_price_tick=False):
        self.closed = False
        self.expired = expired
        self.missing_price_tick = missing_price_tick
        self._account = SimpleNamespace(
            get_margin=lambda _symbol: 3000.0,
            get_commission=lambda _symbol: 2.0,
        )

    def get_trading_calendar(self, start_dt, end_dt):
        days = pd.date_range(start_dt, end_dt, freq='D')
        return pd.DataFrame({
            'date': days,
            'trading': [day.weekday() < 5 for day in days],
        })

    def query_symbol_info(self, symbol):
        row = {
            'instrument_id': symbol,
            'price_tick': 1.0,
            'volume_multiple': 10.0,
            'open_min_limit_order_volume': 1,
            'expire_datetime': 1735689599 if self.expired else 4102444800,
        }
        if self.missing_price_tick:
            row.pop('price_tick')
        return pd.DataFrame([row])

    def close(self):
        self.closed = True


def downloader_factory(*, expired=False, missing_price_tick=False, api_box=None):
    def build(api):
        if api_box is not None:
            api_box.append(api)

        class Task:
            def is_finished(self):
                return True

            def get_progress(self):
                return 100.0

        return Task()

    return build


def test_tqsdk_provider_uses_independent_calendar_and_normalizes_prefixed_csv(
    tmp_path,
):
    box = []
    api = DownloaderApi()

    class Downloader:
        def __init__(
            self,
            _api,
            *,
            symbol_list,
            dur_sec,
            start_dt,
            end_dt,
            csv_file_name,
        ):
            assert symbol_list == 'SHFE.rb2505'
            assert dur_sec == 60
            stamp = int(pd.Timestamp('2025-01-02 09:00', tz='Asia/Shanghai').value)
            Path(csv_file_name).write_text(
                'datetime,datetime_nano,SHFE.rb2505.open,'
                'SHFE.rb2505.high,SHFE.rb2505.low,SHFE.rb2505.close,'
                'SHFE.rb2505.volume,SHFE.rb2505.close_oi\n'
                f'2025-01-02 09:00:00.000000000,{stamp},'
                '3300,3310,3290,3305,100,200\n',
                encoding='utf-8',
            )
            self._finished = True

        def is_finished(self):
            return self._finished

        def get_progress(self):
            return 100.0

    provider = TqSdkDownloadProvider(
        lambda: api,
        downloader_factory=Downloader,
    )
    acquired = provider.download(
        request(),
        tmp_path,
        progress=lambda *_a, **_k: None,
        cancel=lambda: False,
    )
    assert acquired.expected_days == [date(2025, 1, 2), date(2025, 1, 3)]
    assert acquired.observed_days == [date(2025, 1, 2)]
    assert acquired.bars[0]['symbol'] == 'SHFE.rb2505'
    assert acquired.bars[0]['time_ns'] == int(
        pd.Timestamp('2025-01-02 09:00', tz='Asia/Shanghai').value
    )
    assert acquired.instruments[0]['price_tick'] == '1.0'
    assert acquired.instruments[0]['volume_multiple'] == '10.0'
    assert acquired.instruments[0]['margin_per_lot'] == '3000.0'
    assert acquired.instruments[0]['commission_per_lot'] == '2.0'
    assert api.closed is True
    assert box == []


def test_tqsdk_provider_rejects_missing_contract_metadata(tmp_path):
    provider = TqSdkDownloadProvider(
        lambda: DownloaderApi(missing_price_tick=True),
        downloader_factory=downloader_factory(),
    )
    with pytest.raises(DataUnavailableError, match='合约规格'):
        provider.download(
            request(),
            tmp_path,
            progress=lambda *_a, **_k: None,
            cancel=lambda: False,
        )


def test_tqsdk_provider_rejects_contract_expired_before_requested_end(tmp_path):
    provider = TqSdkDownloadProvider(
        lambda: DownloaderApi(expired=True),
        downloader_factory=downloader_factory(expired=True),
    )
    with pytest.raises(DataUnavailableError, match='到期'):
        provider.download(
            request(),
            tmp_path,
            progress=lambda *_a, **_k: None,
            cancel=lambda: False,
        )
