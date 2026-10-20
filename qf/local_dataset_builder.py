"""从已核实的TqSdk连续回放提取可复用实际合约研究数据。"""

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from qf.continuous_results import read_continuous_run
from qf.data_catalog import CoverageReport, DataCapability, DataRequest
from qf.history_store import HistoryStore
from qf.local_data import load_continuous_frame
from qf.research_results import RUN_ID, read_run, run_path


def ensure_local_dataset(results_root, config):
    if config.schema_version != 3 or config.symbol is not None:
        raise ValueError('快速研究目前要求历史主力连续配置')
    if config.precision != 'minute':
        raise ValueError('快速研究目前没有Tick路径，不能降低精度')
    results_root = Path(results_root)
    request = _request(config)
    store = HistoryStore(results_root/'history')
    ready = store.find_ready(request)
    if ready is not None:
        return ready
    candidates = []
    if results_root.exists():
        for path in sorted(results_root.iterdir(), reverse=True):
            if not RUN_ID.fullmatch(path.name):
                continue
            try:
                run = read_run(results_root, path.name)
            except ValueError:
                continue
            saved = run['config']
            if (
                run.get('engine_kind') == 'tqsdk_validation'
                and run.get('schema_version', saved.get('schema_version')) == 3
                and saved.get('continuous') == config.continuous
                and saved.get('bar_seconds') == config.bar_seconds
                and saved.get('start') == str(config.start)
                and saved.get('end') == str(config.end)
                and saved.get('precision') == 'minute'
                and run.get('status') == 'backtest_finished'
            ):
                candidates.append(path.name)
    if not candidates:
        raise ValueError(
            '没有可复用的已验证历史数据；请先完成同区间的TqSdk验证回测，'
            '或取得tq_dl权限后准备本机数据。'
        )
    return build_local_dataset_from_validation(
        results_root, candidates[0], config
    )[0]


def build_local_dataset_from_validation(results_root, run_id, config):
    results_root = Path(results_root)
    run = read_continuous_run(results_root, run_id)
    if run.get('status') != 'backtest_finished':
        raise ValueError('TqSdk验证回放未完成，不能生成本地数据')
    if run.get('engine_kind', 'tqsdk_validation') != 'tqsdk_validation':
        raise ValueError('来源不是TqSdk验证结果')
    if run.get('coverage_check', {}).get('status') != 'verified':
        raise ValueError('TqSdk验证结果的交易日覆盖未通过')
    if config.precision != 'minute':
        raise ValueError('快速研究目前没有Tick路径，不能降低精度')
    if (
        run['config'] != config.public()
    ):
        raise ValueError('验证结果与当前实验配置不一致')
    path = run_path(results_root, run_id)
    try:
        with closing(sqlite3.connect(
            (path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True
        )) as db:
            bars, observed_days = _bars(db, config)
            mapping = _mapping(db)
            instruments = _instruments(db)
    except (OSError, sqlite3.Error, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('验证结果中的本地数据证据不完整') from None
    symbols = {bar['symbol'] for bar in bars}
    if not bars or not mapping:
        raise ValueError('验证结果没有可复用的K线或历史主力映射')
    missing = sorted(symbols-{item['symbol'] for item in instruments})
    if missing:
        raise ValueError('验证结果缺少实际合约规格: '+', '.join(missing))
    request = _request(config)
    store = HistoryStore(results_root/'history')
    ready = store.find_ready(request)
    if ready is not None:
        return ready, load_continuous_frame(store, ready)
    capability = DataCapability(
        status='available',
        reason='从已核实的TqSdk连续回放规范化缓存。',
        minute_available=True,
        tick_available=False,
        source='tqsdk_observed_cache',
    )
    dataset_id = store.create_dataset(
        request, capability.source, capability
    )
    report = CoverageReport(
        expected_days=observed_days,
        observed_days=observed_days,
        issues=[],
    ).validate()
    store.write_instruments(dataset_id, instruments)
    store.write_mapping(dataset_id, mapping)
    store.write_bars(dataset_id, bars)
    store.write_coverage(dataset_id, report)
    return dataset_id, load_continuous_frame(store, dataset_id)


def _request(config):
    return DataRequest(
        continuous=config.continuous,
        symbol=None,
        bar_seconds=config.bar_seconds,
        start=config.start,
        end=config.end,
        precision='minute',
    ).validate()


def _bars(db, config):
    rows = []
    observed = set()
    for stamp, source_symbol, raw in db.execute(
        'SELECT time_ns,source_symbol,data FROM signal_bars ORDER BY time_ns'
    ):
        data = json.loads(raw)
        raw_bar = data.get('raw', {})
        if (
            data.get('source_symbol') != source_symbol
            or not isinstance(raw_bar, dict)
            or data.get('completed') is not True
        ):
            raise ValueError('验证K线记录无效')
        rows.append({
            'symbol': source_symbol,
            'duration': int(config.bar_seconds),
            'time_ns': int(stamp),
            'open': float(raw_bar['open']),
            'high': float(raw_bar['high']),
            'low': float(raw_bar['low']),
            'close': float(raw_bar['close']),
            'volume': float(raw_bar['volume']),
            'close_oi': float(raw_bar['close_oi']),
            'completed': True,
        })
        day = data.get('trading_day')
        if isinstance(day, str) and str(config.start) <= day <= str(config.end):
            observed.add(day)
    return rows, sorted(date.fromisoformat(day) for day in observed)


def _mapping(db):
    result = []
    for raw in db.execute('SELECT data FROM main_changes ORDER BY time_ns'):
        data = json.loads(raw[0])
        result.append({
            'time_ns': int(data['detected_ns']),
            'old_symbol': data.get('old_symbol'),
            'new_symbol': data['new_symbol'],
            'offset': str(data['offset']),
            'reference_ns': data.get('reference_ns'),
        })
    return result


def _instruments(db):
    result = []
    for raw in db.execute('SELECT data FROM contract_specs ORDER BY symbol'):
        data = json.loads(raw[0])
        required = {
            'symbol',
            'price_tick',
            'volume_multiple',
            'margin_per_lot',
            'commission_per_lot',
        }
        if not required <= set(data):
            raise ValueError('验证合约规格字段不完整')
        result.append(data)
    return result
