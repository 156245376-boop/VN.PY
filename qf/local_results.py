"""本地快速回测结果的原子保存、完整性核对与只读摘要。"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from qf.local_backtest import LocalRunResult
from qf.research_config import decimal_value, public_values, validate_research_config

ZERO = Decimal(0)
SENSITIVE_KEYS = ('password', 'passwd', 'token', 'secret', 'credential', 'auth')


def _json(value):
    return json.dumps(
        public_values(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def _safe_metadata(value, *, path='source'):
    if isinstance(value, dict):
        if any(
            _sensitive_key(key)
            for key in value
        ):
            raise ValueError('来源指纹不得包含凭证或认证字段')
        return {str(key): _safe_metadata(item, path=f'{path}.{key}')
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item, path=f'{path}[]') for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f'来源指纹字段不可序列化: {path}')


def _sensitive_key(key):
    text = str(key).lower()
    if '/' in text or '\\' in text or '.' in text:
        return False
    return any(marker in text for marker in SENSITIVE_KEYS)


def _run_id(root):
    root = Path(root)
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S')
    for _attempt in range(20):
        identity = f'{stamp}-{secrets.token_hex(6)}'
        if not (root/identity).exists():
            return identity
    raise OSError('无法生成实验运行编号')


def save_local_result(root, result, source_fingerprint):
    if not isinstance(result, LocalRunResult):
        raise ValueError('本地回测结果无效')
    if result.engine_kind != 'local_research':
        raise ValueError('结果不是本地研究引擎')
    metadata = _safe_metadata(source_fingerprint)
    payload = result.public()
    validate_research_config(payload['config'])
    digest = hashlib.sha256(_json(payload).encode('utf-8')).hexdigest()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id(root)
    path = root/run_id
    path.mkdir()
    db_path = path/'journal.sqlite3'
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.executescript('''
            CREATE TABLE state(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE fills(
                key TEXT PRIMARY KEY,
                order_id TEXT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                offset TEXT NOT NULL,
                volume INTEGER NOT NULL,
                requested_volume INTEGER NOT NULL,
                price TEXT NOT NULL,
                time_ns INTEGER NOT NULL,
                fee TEXT NOT NULL,
                role TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                signal_bar INTEGER,
                execution_bar INTEGER NOT NULL,
                intrabar_resolution TEXT,
                price_source TEXT NOT NULL
            );
            CREATE TABLE local_trades(
                trade_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE signals(
                bar_index INTEGER PRIMARY KEY,
                time_ns INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE equity(
                time_ns INTEGER PRIMARY KEY,
                balance TEXT NOT NULL,
                equity TEXT NOT NULL,
                margin TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE entry_rejections(
                ordinal INTEGER PRIMARY KEY,
                time_ns INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE rolls(
                ordinal INTEGER PRIMARY KEY,
                time_ns INTEGER NOT NULL,
                data TEXT NOT NULL
            );
        ''')
        state = {
            'research_schema': 3,
            'engine_kind': result.engine_kind,
            'engine_version': result.engine_version,
            'compute_backend': result.compute_backend,
            'status': result.status,
            'reason': result.reason,
            'dataset_id': result.dataset_id,
            'config': result.config,
            'source_fingerprint': metadata,
            'result_sha256': digest,
            'result_payload': payload,
        }
        db.executemany(
            'INSERT INTO state VALUES (?,?)',
            [(key, _json(value)) for key, value in state.items()],
        )
        db.executemany(
            'INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(
                fill['key'],
                fill.get('order_id'),
                fill['symbol'],
                fill['direction'],
                fill['offset'],
                int(fill['volume']),
                int(fill['requested_volume']),
                str(fill['price']),
                int(fill['time_ns']),
                str(fill['fee']),
                fill['role'],
                fill['trade_id'],
                fill.get('signal_bar'),
                int(fill['execution_bar']),
                fill.get('intrabar_resolution'),
                fill.get('price_source', 'bar_price'),
            ) for fill in result.fills],
        )
        db.executemany(
            'INSERT INTO local_trades VALUES (?,?)',
            [(trade['trade_id'], _json(trade)) for trade in result.trades],
        )
        db.executemany(
            'INSERT INTO signals VALUES (?,?,?)',
            [(
                int(signal['bar_index']),
                int(signal['time_ns']),
                _json(signal),
            ) for signal in result.signals],
        )
        db.executemany(
            'INSERT INTO equity VALUES (?,?,?,?,?)',
            [(
                int(point['time_ns']),
                str(point['balance']),
                str(point['equity']),
                str(point['margin']),
                _json(point),
            ) for point in result.equity],
        )
        db.executemany(
            'INSERT INTO entry_rejections VALUES (?,?,?)',
            [(
                index,
                int(item['time_ns']),
                _json(item),
            ) for index, item in enumerate(result.entry_rejections)],
        )
        db.executemany(
            'INSERT INTO rolls VALUES (?,?,?)',
            [(
                index,
                int(item['time_ns']),
                _json(item),
            ) for index, item in enumerate(result.rolls)],
        )
    summary = summarize_local_payload(payload, source_fingerprint=metadata)
    (path/'trades.csv').write_text(_trades_csv(payload['trades']), encoding='utf-8-sig')
    (path/'equity.csv').write_text(_equity_csv(payload['equity']), encoding='utf-8-sig')
    (path/'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8',
    )
    return run_id


def _load(db, run_id):
    try:
        state = {
            key: json.loads(value)
            for key, value in db.execute('SELECT key,value FROM state')
        }
    except (json.JSONDecodeError, sqlite3.Error):
        raise ValueError('本地实验状态缺失或损坏') from None
    if (
        state.get('research_schema') != 3
        or state.get('engine_kind') != 'local_research'
        or not isinstance(state.get('result_payload'), dict)
        or not isinstance(state.get('source_fingerprint'), dict)
    ):
        raise ValueError('本地实验版本或引擎身份无效')
    payload = state['result_payload']
    if hashlib.sha256(_json(payload).encode('utf-8')).hexdigest() != (
        state.get('result_sha256')
    ):
        raise ValueError('本地实验主结果完整性校验失败')
    fills = [
        {
            'key': row[0],
            'order_id': row[1],
            'symbol': row[2],
            'direction': row[3],
            'offset': row[4],
            'volume': row[5],
            'requested_volume': row[6],
            'price': str(row[7]),
            'time_ns': row[8],
            'fee': str(row[9]),
            'role': row[10],
            'trade_id': row[11],
            'signal_bar': row[12],
            'execution_bar': row[13],
            'intrabar_resolution': row[14],
            'price_source': row[15],
        }
        for row in db.execute('SELECT * FROM fills ORDER BY time_ns,rowid')
    ]
    if fills != public_values(payload.get('fills', [])):
        raise ValueError('本地实验成交表完整性校验失败')
    trades = [
        json.loads(row[0])
        for row in db.execute(
            'SELECT data FROM local_trades ORDER BY rowid'
        )
    ]
    if trades != payload.get('trades', []):
        raise ValueError('本地实验交易表完整性校验失败')
    equity = [
        json.loads(row[0])
        for row in db.execute('SELECT data FROM equity ORDER BY time_ns')
    ]
    if equity != payload.get('equity', []):
        raise ValueError('本地实验权益表完整性校验失败')
    return state, payload


def read_local_run(root, run_id):
    path = Path(root).resolve()/run_id
    if not (path/'journal.sqlite3').is_file():
        raise ValueError('本地实验结果不存在')
    try:
        with closing(sqlite3.connect(
            (path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True
        )) as db:
            state, payload = _load(db, run_id)
            config = validate_research_config(payload['config'])
            status = payload.get('status')
            if status not in ('backtest_finished', 'stopped', 'failed'):
                raise ValueError('本地实验完成状态无效')
            return {
                'run_id': run_id,
                'config': config.public(),
                'status': status,
                'reason': payload.get('reason'),
                'engine_kind': 'local_research',
                'engine_version': payload.get('engine_version'),
                'compute_backend': payload.get('compute_backend'),
                'dataset_id': payload.get('dataset_id'),
                'precision': payload.get('precision'),
                'source_fingerprint': state['source_fingerprint'],
            }
    except (OSError, sqlite3.Error, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('本地实验文件缺失、版本不支持或记录不完整') from None


def summarize_local_run(root, run_id):
    path = Path(root).resolve()/run_id
    try:
        with closing(sqlite3.connect(
            (path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True
        )) as db:
            state, payload = _load(db, run_id)
            ledger = local_trade_ledger(db)
    except (OSError, sqlite3.Error):
        raise ValueError('本地实验文件缺失或损坏') from None
    summary = summarize_local_payload(
        payload, source_fingerprint=state['source_fingerprint']
    )
    summary['trade_ledger'] = {
        'fee_total': ledger['fee_total'],
        'reconciled': ledger['reconciled'],
    }
    return public_values({'run_id': run_id, **summary})


def summarize_local_payload(payload, *, source_fingerprint):
    config = validate_research_config(payload['config'])
    initial = decimal_value(config.initial_balance)
    final = decimal_value(payload['final_equity'])
    fees = decimal_value(payload['fees'])
    fill_fees = sum(
        (decimal_value(fill['fee']) for fill in payload.get('fills', [])),
        ZERO,
    )
    trade_fees = sum(
        (decimal_value(trade['fee']) for trade in payload.get('trades', [])),
        ZERO,
    )
    cost_reconciled = fill_fees == fees == trade_fees
    peak = initial
    max_drawdown = ZERO
    for point in payload.get('equity', []):
        value = decimal_value(point['equity'])
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak-value)
    return {
        'engine_kind': payload['engine_kind'],
        'engine_version': payload['engine_version'],
        'compute_backend': payload['compute_backend'],
        'dataset_id': payload['dataset_id'],
        'config': config.public(),
        'status': payload['status'],
        'reason': payload['reason'],
        'precision': payload['precision'],
        'fee_multiplier': int(payload.get('fee_multiplier', 1)),
        'cost_source': source_fingerprint.get('cost_source'),
        'initial_balance': str(initial),
        'final_equity': str(final),
        'net_pnl': str(final-initial),
        'gross_pnl': str(decimal_value(payload['gross_pnl'])),
        'commission': str(fees),
        'cost_reconciled': cost_reconciled,
        'fill_count': len(payload.get('fills', [])),
        'closed_trade_count': int(payload['closed_trade_count']),
        'open_position': int(payload['open_position']),
        'max_drawdown_amount': str(max_drawdown),
        'source_fingerprint': source_fingerprint,
    }


def local_run_details(root, run_id):
    path = Path(root).resolve()/run_id
    with closing(sqlite3.connect(
        (path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True
    )) as db:
        _state, payload = _load(db, run_id)
        return {
            'fills': payload.get('fills', []),
            'trades': payload.get('trades', []),
            'equity': payload.get('equity', []),
            'signals': payload.get('signals', []),
            'entry_rejections': payload.get('entry_rejections', []),
            'rolls': payload.get('rolls', []),
        }


def local_trade_ledger(db):
    _state, payload = _load(db, '')
    fills = public_values(payload.get('fills', []))
    trades = []
    for raw in payload.get('trades', []):
        trade = dict(raw)
        trade_fills = [
            {
                'key': fill['key'],
                'order_id': fill.get('order_id'),
                'symbol': fill['symbol'],
                'role': fill['role'],
                'direction': fill['direction'],
                'offset': fill['offset'],
                'volume': fill['volume'],
                'price': fill['price'],
                'time_ns': str(fill['time_ns']),
                'fee': fill['fee'],
                'trade_id': trade['trade_id'],
                'trade_status': trade['status'],
                'trade_net_pnl': trade.get('net_pnl'),
                'entry_price': trade.get('entry_price'),
                'exit_price': trade.get('exit_price'),
                'initial_stop': trade.get('initial_stop'),
                'final_stop': trade.get('final_stop'),
                'exit_reason': trade.get('exit_reason'),
            }
            for fill in fills
            if fill['trade_id'] == trade['trade_id']
        ]
        trade['fills'] = trade_fills
        trades.append(trade)
    trades.sort(key=lambda item: int(item['entry_time_ns']), reverse=True)
    fee_total = sum(
        (decimal_value(fill['fee']) for fill in fills), ZERO
    )
    grouped = sum(
        (decimal_value(trade['fee']) for trade in trades), ZERO
    )
    return {
        'available': True,
        'trades': trades,
        'fills': fills,
        'total': len(trades),
        'truncated': False,
        'fee_total': str(fee_total),
        'fee_reconciled_difference': str(fee_total-grouped),
        'reconciled': fee_total == grouped,
        'reason': '',
    }


def _trades_csv(trades):
    columns = (
        'trade_id', 'status', 'first_symbol', 'last_symbol', 'direction',
        'quantity', 'entry_time_ns', 'entry_price', 'exit_time_ns',
        'exit_price', 'initial_stop', 'final_stop', 'fee', 'gross_pnl',
        'net_pnl', 'exit_reason',
    )
    path = []
    path.append(','.join(columns))
    for trade in trades:
        row = []
        for key in columns:
            value = trade.get(key)
            text = '' if value is None else str(value)
            if any(character in text for character in ',"\r\n'):
                text = '"'+text.replace('"', '""')+'"'
            row.append(text)
        path.append(','.join(row))
    return '\n'.join(path)+'\n'


def _equity_csv(points):
    columns = (
        'time_ns', 'balance', 'unrealized_gross', 'equity', 'margin',
        'last_fill', 'bar_index',
    )
    output = []
    output.append(','.join(columns))
    for point in points:
        output.append(','.join(
            '' if point.get(key) is None else str(point.get(key))
            for key in columns
        ))
    return '\n'.join(output)+'\n'
