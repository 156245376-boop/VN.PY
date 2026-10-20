"""权限感知的历史数据准备管线；网络适配与规范化存储分离。"""

import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import isfinite
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
            expected_days = self._expected_days(api, request)
            instrument = self._instrument(api, request)
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
        except (DataCancelled, DataPermissionError, DataUnavailableError):
            raise
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
        columns = {
            name: self._column(frame, request.symbol, name)
            for name in ('open', 'high', 'low', 'close', 'volume', 'close_oi')
        }
        if any(value is None for value in columns.values()):
            raise DataUnavailableError('下载文件字段不完整。')
        if 'datetime_nano' in frame:
            stamps = pd.to_numeric(
                frame['datetime_nano'], errors='raise'
            ).astype('int64')
        elif 'datetime' in frame:
            stamps = pd.to_datetime(frame['datetime']).dt.tz_localize(
                'Asia/Shanghai').astype('int64')
        else:
            raise DataUnavailableError('下载文件缺少K线时间。')
        bars = []
        observed = set()
        seen = set()
        for position, stamp in enumerate(stamps):
            stamp = int(stamp)
            if stamp <= 0 or stamp in seen:
                raise DataUnavailableError('下载文件K线时间重复或无效。')
            seen.add(stamp)
            values = {
                name: float(frame.iloc[position][column])
                for name, column in columns.items()
            }
            if (
                any(not isfinite(value) for value in values.values())
                or min(values[name] for name in ('open', 'high', 'low', 'close'))
                <= 0
                or values['high']
                < max(values['open'], values['low'], values['close'])
                or values['low']
                > min(values['open'], values['high'], values['close'])
                or values['volume'] < 0
                or values['close_oi'] < 0
            ):
                raise DataUnavailableError('下载文件包含无效K线。')
            day = self._trading_day(stamp)
            observed.add(day)
            bars.append(dict(
                symbol=request.symbol, duration=request.bar_seconds,
                time_ns=stamp, **values, completed=True))
        observed_days = sorted(observed)
        return AcquiredData(
            bars=bars, instruments=[instrument], mapping=[{
                'time_ns': bars[0]['time_ns'], 'old_symbol': None,
                'new_symbol': request.symbol, 'offset': '0',
                'reference_ns': None}],
            expected_days=expected_days, observed_days=observed_days, issues=[])

    @staticmethod
    def _expected_days(api, request):
        try:
            calendar = api.get_trading_calendar(request.start, request.end)
        except Exception:
            raise DataUnavailableError('无法取得独立交易日历。') from None
        if (
            not isinstance(calendar, pd.DataFrame)
            or not {'date', 'trading'} <= set(calendar.columns)
        ):
            raise DataUnavailableError('交易日历字段不完整。')
        days = []
        for row in calendar.itertuples(index=False):
            day = pd.Timestamp(row.date).date()
            if request.start <= day <= request.end and bool(row.trading):
                days.append(day)
        if not days:
            raise DataUnavailableError('请求范围内没有交易日。')
        if len(days) != len(set(days)):
            raise DataUnavailableError('交易日历存在重复日期。')
        return days

    @staticmethod
    def _instrument(api, request):
        try:
            info = api.query_symbol_info(request.symbol)
        except Exception:
            raise DataUnavailableError('无法取得实际合约规格。') from None
        if not isinstance(info, pd.DataFrame) or info.empty:
            raise DataUnavailableError('实际合约规格不存在。')
        row = info.iloc[0]
        required = {'price_tick', 'volume_multiple'}
        if not required <= set(info.columns):
            raise DataUnavailableError('实际合约规格字段不完整。')
        try:
            price_tick = Decimal(str(row['price_tick']))
            volume_multiple = Decimal(str(row['volume_multiple']))
            min_lots = int(
                row.get('open_min_limit_order_volume')
                or row.get('min_limit_order_volume')
                or 1
            )
        except (TypeError, ValueError, ArithmeticError):
            raise DataUnavailableError('实际合约规格无效。') from None
        if price_tick <= 0 or volume_multiple <= 0 or min_lots < 1:
            raise DataUnavailableError('实际合约规格无效。')
        expire = row.get('expire_datetime')
        if expire is not None and not pd.isna(expire):
            try:
                expire_seconds = float(expire)
            except (TypeError, ValueError):
                raise DataUnavailableError('合约到期时间无效。') from None
            request_end = pd.Timestamp(
                request.end, tz='Asia/Shanghai'
            )+pd.Timedelta(days=1)
            if isfinite(expire_seconds) and expire_seconds < request_end.timestamp():
                raise DataUnavailableError('实际合约在请求结束日前已经到期。')
        account = getattr(api, '_account', None)
        if (
            account is None
            or not callable(getattr(account, 'get_margin', None))
            or not callable(getattr(account, 'get_commission', None))
        ):
            raise DataUnavailableError('SDK账户未提供模拟保证金和手续费模型。')
        try:
            margin = Decimal(str(account.get_margin(request.symbol)))
            commission = Decimal(str(account.get_commission(request.symbol)))
        except (TypeError, ValueError, ArithmeticError):
            raise DataUnavailableError('SDK模拟保证金或手续费无效。') from None
        if (
            not margin.is_finite()
            or not commission.is_finite()
            or margin <= 0
            or commission < 0
        ):
            raise DataUnavailableError('SDK模拟保证金或手续费无效。')
        return {
            'symbol': request.symbol,
            'price_tick': str(price_tick),
            'volume_multiple': str(volume_multiple),
            'min_open_lots': min_lots,
            'lot_step': 1,
            'margin_per_lot': str(margin),
            'commission_per_lot': str(commission),
            'cost_source': 'tqsdk_sim_model_current_snapshot',
        }

    @staticmethod
    def _column(frame, symbol, name):
        for candidate in (f'{symbol}.{name}', name):
            if candidate in frame:
                return candidate
        return None

    @staticmethod
    def _trading_day(stamp):
        from tqsdk.datetime import _get_trading_day_from_timestamp
        return pd.Timestamp(
            _get_trading_day_from_timestamp(stamp), unit='ns', tz='UTC'
        ).tz_convert('Asia/Shanghai').date()
