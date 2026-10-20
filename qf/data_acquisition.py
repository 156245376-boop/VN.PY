"""权限感知的历史数据准备管线；网络适配与规范化存储分离。"""

import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from qf.data_catalog import CoverageReport, DataCapability


class DataPermissionError(ValueError):
    pass


class DataUnavailableError(ValueError):
    pass


class DataCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class AcquiredData:
    bars: list[dict]
    instruments: list[dict]
    mapping: list[dict]
    expected_days: list[date]
    observed_days: list[date]
    issues: list[str]


def prepare_dataset(provider, store, request, progress, cancel):
    request.validate()
    capability = provider.probe(request).validate()
    if capability.status != 'available':
        return {'status': capability.status, 'reason': capability.reason,
                'dataset_id': None}
    precision_available = (capability.minute_available if request.precision == 'minute'
                           else capability.tick_available)
    if not precision_available:
        return {'status': 'unsupported', 'reason': '账户或数据源不支持所选精度。',
                'dataset_id': None}
    dataset_id = store.create_dataset(request, capability.source, capability)
    try:
        with tempfile.TemporaryDirectory(dir=store.root, prefix='dataset-') as temp:
            acquired = provider.download(request, Path(temp), progress, cancel)
        if not isinstance(acquired, AcquiredData):
            raise DataUnavailableError('数据源没有返回规范化结果。')
        report = CoverageReport(
            expected_days=acquired.expected_days,
            observed_days=acquired.observed_days,
            issues=acquired.issues).validate()
        if acquired.instruments:
            store.write_instruments(dataset_id, acquired.instruments)
        if acquired.mapping:
            store.write_mapping(dataset_id, acquired.mapping)
        store.write_bars(dataset_id, acquired.bars)
        store.write_coverage(dataset_id, report)
        return {'status': 'ready' if report.complete() else 'incomplete',
                'reason': '数据准备完成。' if report.complete() else '数据覆盖不完整。',
                'dataset_id': dataset_id,
                'coverage': report.public()}
    except DataPermissionError as exc:
        store.set_status(dataset_id, 'failed')
        return {'status': 'permission_required', 'reason': str(exc),
                'dataset_id': None}
    except DataCancelled:
        store.set_status(dataset_id, 'cancelled')
        return {'status': 'cancelled', 'reason': '数据准备已取消。',
                'dataset_id': dataset_id}
    except (DataUnavailableError, OSError, TypeError, ValueError) as exc:
        store.set_status(dataset_id, 'failed')
        return {'status': 'failed',
                'reason': str(exc) or '数据源返回内容无效。',
                'dataset_id': dataset_id}


class TqSdkDownloadProvider:
    """固定实际合约的官方DataDownloader适配；权限在下载时核实。"""

    def __init__(self, api_factory, *, downloader_factory=None):
        self.api_factory = api_factory
        self.downloader_factory = downloader_factory

    def probe(self, request):
        if request.symbol is None:
            return DataCapability(
                status='unsupported',
                reason='批量下载必须先核实并选择实际合约。',
                minute_available=False, tick_available=False,
                source='tqsdk_downloader')
        return DataCapability(
            status='available', reason='下载时核实账户权限与覆盖。',
            minute_available=True, tick_available=True,
            source='tqsdk_downloader')

    def download(self, request, temp_dir, progress, cancel):
        if request.symbol is None:
            raise DataUnavailableError('缺少实际合约。')
        if cancel():
            raise DataCancelled()
        if self.downloader_factory is None:
            from tqsdk.tools import DataDownloader
            downloader_factory = DataDownloader
        else:
            downloader_factory = self.downloader_factory
        api = self.api_factory()
        csv_path = Path(temp_dir)/'download.csv'
        try:
            task = downloader_factory(
                api, symbol_list=request.symbol,
                dur_sec=0 if request.precision == 'tick' else request.bar_seconds,
                start_dt=request.start, end_dt=request.end,
                csv_file_name=str(csv_path))
            last_percent = None
            while not task.is_finished():
                if cancel():
                    raise DataCancelled()
                api.wait_update()
                percent = int(task.get_progress())
                if percent != last_percent:
                    progress('download', percent=percent)
                    last_percent = percent
        except Exception as exc:
            text = str(exc)
            if 'tq_dl' in text or '权限' in text or 'permission' in text.lower():
                raise DataPermissionError('需要天勤tq_dl数据下载权限。') from None
            raise DataUnavailableError('历史数据下载未完成。') from None
        finally:
            try:
                api.close()
            except Exception:
                pass
        if cancel():
            raise DataCancelled()
        if not csv_path.is_file():
            raise DataUnavailableError('下载任务未生成数据文件。')
        progress('validate', percent=100)
        frame = pd.read_csv(csv_path)
        if frame.empty:
            raise DataUnavailableError('下载文件没有有效数据。')
        required = {'datetime', 'open', 'high', 'low', 'close', 'volume', 'close_oi'}
        if not required <= set(frame.columns):
            raise DataUnavailableError('下载文件字段不完整。')
        stamps = pd.to_datetime(frame['datetime']).dt.tz_localize(
            'Asia/Shanghai').astype('int64')
        bars = []
        observed = set()
        for stamp, (_, row) in zip(stamps, frame.iterrows(), strict=True):
            day = pd.Timestamp(int(stamp), unit='ns', tz='UTC').tz_convert(
                'Asia/Shanghai').date()
            observed.add(day)
            bars.append(dict(
                symbol=request.symbol, duration=request.bar_seconds,
                time_ns=int(stamp), open=row['open'], high=row['high'],
                low=row['low'], close=row['close'], volume=row['volume'],
                close_oi=row['close_oi'], completed=True))
        observed_days = sorted(observed)
        expected_days = [day for day in pd.bdate_range(
            request.start, request.end).date if day in observed]
        return AcquiredData(
            bars=bars, instruments=[], mapping=[{
                'time_ns': bars[0]['time_ns'], 'old_symbol': None,
                'new_symbol': request.symbol, 'offset': '0',
                'reference_ns': None}],
            expected_days=expected_days, observed_days=observed_days, issues=[])
