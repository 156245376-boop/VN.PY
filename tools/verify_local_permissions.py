"""只读核对快期账户日历、分钟数据、历史主力和可选tq_dl权限。"""

import argparse
import json
import math
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qf.credentials import SavedLogin


def _date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError('日期必须为YYYY-MM-DD') from None


def probe(credentials, *, continuous, start, end, bar_seconds, probe_tick=False,
          download=False, sdk=None):
    if not isinstance(credentials, tuple) or len(credentials) != 2:
        raise ValueError('凭证无效')
    if sdk is None:
        import tqsdk as sdk
    from tqsdk.tools import DataDownloader

    report = {
        'status': 'checking',
        'continuous': continuous,
        'start': str(start),
        'end': str(end),
        'bar_seconds': bar_seconds,
        'calendar': None,
        'actual_symbol': None,
        'minute_bars': 0,
        'first_bar_ns': None,
        'last_bar_ns': None,
        'mapping_observed': False,
        'tick_available': None,
        'tq_dl_feature': None,
        'download_verified': None,
    }
    api = sdk.TqApi(
        account=sdk.TqSim(init_balance=100000),
        backtest=sdk.TqBacktest(start_dt=start, end_dt=end),
        auth=sdk.TqAuth(*credentials),
    )
    try:
        calendar = api.get_trading_calendar(start, end)
        trading_days = [
            str(row.date)
            for row in calendar.itertuples(index=False)
            if bool(row.trading)
        ]
        if not trading_days:
            raise RuntimeError('trading_calendar_empty')
        report['calendar'] = {
            'days': len(trading_days),
            'first': trading_days[0],
            'last': trading_days[-1],
        }
        main = api.get_quote(continuous)
        deadline = time.monotonic()+30
        while not main.underlying_symbol:
            if time.monotonic() > deadline:
                raise TimeoutError('historical_main_missing')
            api.wait_update(deadline=time.monotonic()+1)
        actual = main.underlying_symbol
        report['actual_symbol'] = actual
        report['mapping_observed'] = isinstance(actual, str) and bool(actual)
        quote = api.get_quote(actual)
        bars = api.get_kline_serial(actual, bar_seconds, data_length=10000)
        ticks = None
        if probe_tick:
            try:
                ticks = api.get_tick_serial(actual, data_length=2)
            except Exception:
                report['tick_available'] = False
        first = last = None
        try:
            while True:
                api.wait_update(deadline=time.monotonic()+1)
                if len(bars) and int(bars.iloc[-2].datetime) > 0:
                    completed = bars.iloc[:-1]
                    stamps = completed['datetime'].astype('int64')
                    first = int(stamps.min()) if first is None else first
                    last = int(stamps.max()) if last is None else last
                    report['minute_bars'] = len(completed)
                    report['first_bar_ns'] = str(first)
                    report['last_bar_ns'] = str(last)
                if (
                    ticks is not None
                    and 'datetime' in ticks.columns
                    and not ticks.empty
                    and int(ticks.iloc[-1]['datetime']) > 0
                ):
                    report['tick_available'] = True
                if quote.expire_datetime and math.isfinite(quote.expire_datetime):
                    report['contract_expire'] = int(quote.expire_datetime)
        except sdk.BacktestFinished:
            pass
        if not report['minute_bars']:
            raise RuntimeError('historical_minute_missing')
        report['tq_dl_feature'] = bool(
            api._auth._has_feature('tq_dl')
        )
        if download:
            if not report['tq_dl_feature']:
                report['download_verified'] = False
            else:
                with tempfile.TemporaryDirectory(prefix='qf-dl-probe-') as temp:
                    csv_path = Path(temp)/'probe.csv'
                    task = DataDownloader(
                        api,
                        symbol_list=actual,
                        dur_sec=bar_seconds,
                        start_dt=start,
                        end_dt=min(end, date.fromisoformat(trading_days[0])),
                        csv_file_name=str(csv_path),
                    )
                    while not task.is_finished():
                        api.wait_update(deadline=time.monotonic()+1)
                    report['download_verified'] = bool(
                        csv_path.is_file() and csv_path.stat().st_size
                    )
        report['status'] = 'verified'
        return report
    finally:
        try:
            api.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--credential-root',
        type=Path,
        required=True,
        help='保存Windows凭证时使用的工作区根目录',
    )
    parser.add_argument('--continuous', default='KQ.m@SHFE.rb')
    parser.add_argument('--start', type=_date, default=date(2025, 3, 3))
    parser.add_argument('--end', type=_date, default=date(2025, 3, 7))
    parser.add_argument('--bar-seconds', type=int, default=60)
    parser.add_argument('--probe-tick', action='store_true')
    parser.add_argument('--no-download', action='store_true')
    args = parser.parse_args()
    login = SavedLogin(args.credential_root)
    info = login.info()
    if not info.get('saved'):
        print(json.dumps({
            'status': 'credentials_missing',
            'reason': '该工作区根目录没有保存的快期凭证。',
        }, ensure_ascii=False, indent=2))
        return 2
    credentials = login.resolve(info['user'], '')
    report = probe(
        credentials,
        continuous=args.continuous,
        start=args.start,
        end=args.end,
        bar_seconds=args.bar_seconds,
        probe_tick=args.probe_tick,
        download=not args.no_download,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
