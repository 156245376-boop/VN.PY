"""有界、可核实的回测账户证据；不读取认证对象或其他SDK字段。"""

import json
import math
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from qf.research_config import decimal_value

SUMMARY = ('balance', 'float_profit', 'margin', 'available', 'commission')
TOTAL_KEYS = {'commission_total', 'roll_commission', 'actual_fill_count',
              'closed_trade_count', 'open_position'}
POSITION_FIELDS = ('pos_long', 'pos_short', 'open_price_long', 'open_price_short',
                   'float_profit', 'margin')
ORDER_FIELDS = ('direction', 'offset', 'status', 'volume_orign', 'volume_left', 'limit_price')
TRADE_FIELDS = ('direction', 'offset', 'volume', 'price', 'trade_date_time')
TRIGGERS = {'bar_close', 'fill', 'protection', 'roll', 'terminal'}
STATUSES = {'active', 'last_snapshot', 'legacy_partial'}
ROLES = {'strategy_open', 'strategy_close', 'roll_out', 'roll_in'}
LIMIT = 500


def _value(row, key, default=None):
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _number(value):
    if type(value) in (int, float) and math.isfinite(value):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return float(value)
    return None


def _integer(value, *, allow_none=True, minimum=0):
    if value is None and allow_none:
        return None
    if type(value) is not int or value < minimum:
        return None
    return value


def _symbol(key, row):
    exchange, instrument = _value(row, 'exchange_id'), _value(row, 'instrument_id')
    if isinstance(exchange, str) and isinstance(instrument, str) and exchange and instrument:
        return f'{exchange}.{instrument}'
    if isinstance(_value(row, 'symbol'), str):
        return _value(row, 'symbol')
    return key if isinstance(key, str) and '.' in key and not key.startswith('_') else None


def _rows(collection, fields):
    result = []
    items = getattr(collection, 'items', lambda: ())()
    for key, row in items:
        if str(key).startswith('_'):
            continue
        symbol = _symbol(key, row)
        if symbol is None:
            continue
        clean = {'symbol': symbol}
        for field in fields:
            value = _value(row, field)
            if field == 'trade_date_time':
                clean[field] = str(value) if type(value) in (int, float) and value > 0 else None
            else:
                clean[field] = _number(value) if field not in {
                    'direction', 'offset', 'status'} else (
                    value if value in ('BUY', 'SELL', 'OPEN', 'CLOSE', 'CLOSETODAY',
                                       'ALIVE', 'FINISHED') else None)
        result.append(clean)
    return result[-LIMIT:], len(result) > LIMIT


def _totals(raw):
    if not isinstance(raw, Mapping) or set(raw) != TOTAL_KEYS:
        raise ValueError('账户汇总字段不完整')
    commission = decimal_value(raw['commission_total'])
    roll = decimal_value(raw['roll_commission'])
    if commission < 0 or roll < 0 or roll > commission:
        raise ValueError('账户费用汇总无效')
    counts = {}
    for key in ('actual_fill_count', 'closed_trade_count'):
        value = raw[key]
        if type(value) is not int or value < 0:
            raise ValueError('账户交易计数无效')
        counts[key] = value
    position = raw['open_position']
    if type(position) is not int:
        raise ValueError('账户持仓汇总无效')
    return {'commission_total': str(commission), 'roll_commission': str(roll),
            **counts, 'open_position': position}


def account_snapshot(api, *, time_ns, totals, status, details=True):
    if type(time_ns) is not int or time_ns < 0 or status not in STATUSES - {'legacy_partial'}:
        raise ValueError('账户快照状态无效')
    summary = _totals(totals)
    account = api.get_account()
    for key in SUMMARY:
        summary[key] = _number(_value(account, key))
    if details:
        positions, position_cut = _rows(api.get_position(), POSITION_FIELDS)
        orders, order_cut = _rows(api.get_order(), ORDER_FIELDS)
        trades, trade_cut = _rows(api.get_trade(), TRADE_FIELDS)
    else:
        positions, orders, trades = [], [], []
        position_cut = order_cut = trade_cut = False
    return {
        'kind': 'backtest', 'time_ns': str(time_ns), 'status': status,
        'summary': summary, 'positions': positions, 'orders': orders, 'trades': trades,
        'truncated': {'positions': position_cut, 'orders': order_cut, 'trades': trade_cut},
        'availability': {'summary': 'recorded',
                         'positions': 'recorded' if details else 'unrecorded',
                         'orders': 'recorded' if details else 'unrecorded',
                         'trades': 'recorded' if details else 'unrecorded'},
    }


def compact_account_snapshot(snapshot):
    """分钟内账户只保存汇总，完整持仓/委托/成交留给变化时点和末次快照。"""
    if not isinstance(snapshot, dict) or snapshot.get('kind') != 'backtest':
        raise ValueError('账户快照格式无效')
    return {
        'kind': 'backtest', 'time_ns': snapshot.get('time_ns'),
        'status': snapshot.get('status'), 'summary': dict(snapshot.get('summary') or {}),
        'positions': [], 'orders': [], 'trades': [],
        'truncated': {'positions': False, 'orders': False, 'trades': False},
        'availability': {'summary': 'recorded', 'positions': 'unrecorded',
                         'orders': 'unrecorded', 'trades': 'unrecorded'},
    }


def account_schema(db):
    marker = db.execute("SELECT value FROM state WHERE key='account_schema_version'").fetchone()
    names = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    tables = names & {'research_accounts', 'research_fill_fees'}
    if marker is None and not tables:
        return 0
    if marker != ('1',) or tables != {'research_accounts', 'research_fill_fees'}:
        raise ValueError('账户证据模型不完整')
    return 1


def enable_account_evidence(journal):
    if journal.get('mode') != 'backtest':
        raise ValueError('仅历史回测提供完整账户证据')
    if account_schema(journal.db) == 1:
        return
    with journal.db:
        journal.db.execute('''CREATE TABLE research_accounts(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, time_ns INTEGER NOT NULL,
            trigger TEXT NOT NULL, data TEXT NOT NULL)''')
        journal.db.execute('''CREATE TABLE research_fill_fees(
            fill_key TEXT PRIMARY KEY, amount TEXT NOT NULL, role TEXT NOT NULL)''')
        journal.db.execute('CREATE INDEX research_account_time ON research_accounts(time_ns,seq)')
        journal.db.execute("INSERT OR REPLACE INTO state VALUES ('account_schema_version','1')")


def save_account(journal, snapshot, *, trigger):
    if trigger not in TRIGGERS:
        raise ValueError('账户采样触发无效')
    if account_schema(journal.db) != 1:
        raise ValueError('账户证据模型尚未启用')
    if not isinstance(snapshot, dict) or snapshot.get('kind') != 'backtest':
        raise ValueError('账户快照格式无效')
    stamp = snapshot.get('time_ns')
    if not isinstance(stamp, str) or not stamp.isdigit():
        raise ValueError('账户快照时间无效')
    data = {key: snapshot[key] for key in (
        'kind', 'time_ns', 'status', 'summary', 'positions', 'truncated', 'availability')}
    with journal.db:
        journal.db.execute('INSERT INTO research_accounts(time_ns,trigger,data) VALUES (?,?,?)',
                           (int(stamp), trigger,
                            json.dumps(data, ensure_ascii=False, sort_keys=True)))


def _decode(raw):
    value = json.loads(raw)
    summary = value.get('summary', {})
    for key in ('balance', 'float_profit', 'margin', 'available', 'commission'):
        summary[key] = _number(summary.get(key))
    return value


def _legacy(db):
    state = {key: json.loads(value) for key, value in db.execute('SELECT * FROM state')}
    last = db.execute('SELECT balance,commission FROM equity ORDER BY time_ns DESC LIMIT 1') \
        .fetchone()
    fills = db.execute('SELECT count(*) FROM fills').fetchone()[0]
    try:
        trades = db.execute('SELECT count(*) FROM logical_trades').fetchone()[0]
    except sqlite3.Error:
        trades = 0
    fee = state.get('total_commission', state.get('sdk_statistics', {}).get('commission'))
    final = state.get('final_positions')
    position = (sum(pair[0]-pair[1] for pair in final.values())
                if isinstance(final, dict) else None)
    summary = {'balance': _number(last[0]) if last else None,
               'float_profit': None, 'margin': None, 'available': None,
               'commission': None,
               'commission_total': str(decimal_value(fee)) if fee is not None else None,
               'roll_commission': None, 'actual_fill_count': fills,
               'closed_trade_count': trades, 'open_position': position}
    return {'kind': 'backtest', 'time_ns': None, 'status': 'legacy_partial',
            'summary': summary, 'positions': [], 'orders': [], 'trades': [],
            'truncated': {'positions': False, 'orders': False, 'trades': False},
            'availability': {'summary': 'partial', 'positions': 'partial',
                             'orders': 'unrecorded', 'trades': 'recorded'}}


def read_account(db, *, at_ns=None):
    if at_ns is not None and (type(at_ns) is not int or at_ns < 0):
        raise ValueError('账户读取时间无效')
    if account_schema(db) == 0:
        return _legacy(db)
    sql = 'SELECT data FROM research_accounts'
    params = ()
    if at_ns is not None:
        sql += ' WHERE time_ns<=?'
        params = (at_ns,)
    row = db.execute(sql+' ORDER BY time_ns DESC,seq DESC LIMIT 1', params).fetchone()
    return _decode(row[0]) if row else None


def account_window(db, *, first_ns, as_of_ns, limit=LIMIT):
    if (type(first_ns) is not int or type(as_of_ns) is not int
            or first_ns < 0 or as_of_ns < first_ns or type(limit) is not int
            or not 1 <= limit <= LIMIT):
        raise ValueError('账户历史窗口无效')
    if account_schema(db) == 0:
        return {'seed': None, 'samples': [], 'truncated': False}
    seed = db.execute('SELECT data FROM research_accounts WHERE time_ns<? '
                      'ORDER BY time_ns DESC,seq DESC LIMIT 1', (first_ns,)).fetchone()
    rows = db.execute('SELECT data FROM research_accounts WHERE time_ns BETWEEN ? AND ? '
                      'ORDER BY time_ns,seq LIMIT ?', (first_ns, as_of_ns, limit+1)).fetchall()
    return {'seed': _decode(seed[0]) if seed else None,
            'samples': [_decode(row[0]) for row in rows[:limit]],
            'truncated': len(rows) > limit}


def normalize_fill_fees(entries, expected_keys):
    if entries is None or not isinstance(entries, list):
        raise ValueError('成交费用证据缺失')
    result, keys = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'fill_key', 'amount', 'role'}:
            raise ValueError('成交费用字段无效')
        key, role = entry['fill_key'], entry['role']
        amount = decimal_value(entry['amount'])
        if (not isinstance(key, str) or key in keys or role not in ROLES or amount < 0
                or not amount.is_finite()):
            raise ValueError('成交费用内容无效')
        keys.add(key)
        result.append(dict(fill_key=key, amount=str(amount), role=role))
    if keys != set(expected_keys) or len(result) != len(expected_keys):
        raise ValueError('成交费用未与成交一一对应')
    return result


def insert_fill_fees(db, entries):
    for entry in entries:
        old = db.execute('SELECT amount,role FROM research_fill_fees WHERE fill_key=?',
                         (entry['fill_key'],)).fetchone()
        if old is not None and old != (entry['amount'], entry['role']):
            raise ValueError('既有成交费用被改写')
        if old is None:
            db.execute('INSERT INTO research_fill_fees VALUES (?,?,?)',
                       (entry['fill_key'], entry['amount'], entry['role']))


def costs_reconciled(sdk_total, fill_total):
    return abs(decimal_value(sdk_total)-decimal_value(fill_total)) <= Decimal('0.01')


def fill_fee_total(db, *, role=None):
    where, params = (' WHERE role=?', (role,)) if role else ('', ())
    return sum((decimal_value(row[0]) for row in db.execute(
        'SELECT amount FROM research_fill_fees'+where, params)), Decimal(0))


def account_totals(db):
    actual = db.execute('SELECT count(*) FROM fills').fetchone()[0]
    total = fill_fee_total(db)
    roll = fill_fee_total(db, role='roll_out') + fill_fee_total(db, role='roll_in')
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'logical_trades' in tables:
        closed = db.execute('SELECT count(*) FROM logical_trades').fetchone()[0]
    else:
        position = closed = 0
        for volume, direction in db.execute(
                'SELECT volume,direction FROM fills ORDER BY time_ns,rowid'):
            previous = position
            position += volume if direction == 'BUY' else -volume
            if previous and not position:
                closed += 1
    position = db.execute("SELECT coalesce(sum(CASE WHEN direction='BUY' THEN volume "
                          "ELSE -volume END),0) FROM fills").fetchone()[0]
    return {'commission_total': str(total), 'roll_commission': str(roll),
            'actual_fill_count': actual, 'closed_trade_count': closed,
            'open_position': position}
