"""从已保存的风险事件生成有界保护段；展示层不重新计算交易规则。"""

import json
from decimal import Decimal

from qf.continuous_journal import logical_from_dict
from qf.continuous_risk import logical_stop
from qf.research_config import decimal_value
from qf.trade_risk import ContractSpec

LIMIT = 5000
ACTIVE_KINDS = {'fill', 'protection', 'sealed', 'reconciled', 'closed'}


def _event_rows(db, first_ns, as_of_ns, limit):
    seed = db.execute(
        'SELECT rowid,* FROM risk_events WHERE time_ns<? '
        'ORDER BY time_ns DESC,rowid DESC LIMIT 500', (first_ns,)).fetchall()
    window = db.execute(
        'SELECT rowid,* FROM risk_events WHERE time_ns BETWEEN ? AND ? '
        'ORDER BY time_ns,rowid LIMIT ?', (first_ns, as_of_ns, limit+1)).fetchall()
    rows = sorted({row[0]: row for row in [*seed, *window]}.values(),
                  key=lambda row: (row[2], row[0]))
    return rows, len(window) > limit or len(seed) >= 500


def _config(db):
    row = db.execute("SELECT value FROM state WHERE key='config'").fetchone()
    return json.loads(row[0]) if row else {}


def _payload(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _risk(raw):
    value = _payload(raw)
    if 'floor_gross' in value:
        return logical_from_dict(value)
    return value


def _trade_id(risk):
    return _field(risk, 'trade_id')


def _quantity(risk):
    return _field(risk, 'quantity')


def _field(risk, name, default=None):
    return risk.get(name, default) if isinstance(risk, dict) else getattr(risk, name, default)


def _mappings(db):
    try:
        return [(row[0], _payload(row[1])) for row in db.execute(
            'SELECT time_ns,data FROM main_changes ORDER BY time_ns,rowid')]
    except Exception:
        return []


def _offset(db, mappings, symbol, stamp):
    value = Decimal(0)
    for time_ns, mapping in mappings:
        if time_ns > stamp:
            break
        if mapping.get('new_symbol') == symbol:
            value = decimal_value(mapping.get('offset', 0))
    if not mappings:
        raw = db.execute("SELECT value FROM state WHERE key='signal_offset'").fetchone()
        if raw is not None:
            value = decimal_value(json.loads(raw[0]))
    return value


def _specs(db):
    try:
        return {row[0]: ContractSpec(**json.loads(row[1])) for row in db.execute(
            'SELECT symbol,data FROM contract_specs')}
    except Exception:
        return {}


def _symbol(db, row, config, mappings):
    payload, stamp = _payload(row[4]), row[2]
    symbol = payload.get('symbol') or payload.get('source_symbol')
    if isinstance(symbol, str) and symbol:
        return symbol
    if isinstance(config.get('symbol'), str):
        return config['symbol']
    for time_ns, mapping in reversed(mappings):
        if time_ns <= stamp and isinstance(mapping.get('new_symbol'), str):
            return mapping['new_symbol']
    return None


def _stop(risk, spec):
    if isinstance(risk, dict):
        value = risk.get('stop_price')
        return decimal_value(value) if value is not None else None
    if not spec or not risk.quantity:
        return None
    return logical_stop(risk, spec=spec)


def _segment(trade_id, symbol, kind, start, end, actual, offset, quantity, stage, reason):
    return dict(trade_id=trade_id, source_symbol=symbol, kind=kind,
                start_ns=str(start), end_ns=str(end), actual_price=str(actual),
                display_price=str(actual-offset), quantity=quantity,
                stage=stage, reason=reason)


def _initial_plan(db, trade_id, config, mappings):
    fill = db.execute(
        "SELECT rowid,* FROM risk_events WHERE kind='fill' "
        "AND json_extract(risk,'$.trade_id')=? AND json_extract(risk,'$.quantity')>0 "
        "ORDER BY time_ns,rowid LIMIT 1", (trade_id,)).fetchone()
    if fill is None:
        return None
    source = _symbol(db, fill, config, mappings)
    if source is None:
        return None
    signal = db.execute(
        "SELECT payload FROM risk_events WHERE kind='signal' AND time_ns<=? "
        "ORDER BY time_ns DESC,rowid DESC LIMIT 1", (fill[2],)).fetchone()
    if signal is None:
        return None
    payload = _payload(signal[0])
    plan = payload.get('entry_plan')
    if not isinstance(plan, dict) or plan.get('stop_price') is None:
        return None
    return source, fill[2], plan


def protection_window(db, *, first_ns, as_of_ns, series, symbol=None, limit=LIMIT):
    if (type(first_ns) is not int or type(as_of_ns) is not int
            or min(first_ns, as_of_ns) < 0 or as_of_ns < first_ns
            or series not in ('signal', 'actual') or type(limit) is not int
            or not 1 <= limit <= LIMIT):
        raise ValueError('保护轨迹窗口无效')
    config, mappings, specs = _config(db), _mappings(db), _specs(db)
    rows, truncated = _event_rows(db, first_ns, as_of_ns, limit)
    prepared = []
    for row in rows:
        risk = _risk(row[5])
        actual_symbol = _symbol(db, row, config, mappings)
        prepared.append(dict(row=row, stamp=row[2], kind=row[3], payload=_payload(row[4]),
                             risk=risk, trade_id=_trade_id(risk), symbol=actual_symbol,
                             stop=_stop(risk, specs.get(actual_symbol))))
    seeds = {}
    window = []
    for item in prepared:
        if item['stamp'] < first_ns:
            seeds[(item['trade_id'], item['symbol'])] = item
        else:
            window.append(item)
    prepared = sorted(
        [*seeds.values(), *window],
        key=lambda item: (item['stamp'], item['row'][0]))

    segments, pivots = [], []
    trades = {}
    for item in prepared:
        if item['trade_id']:
            trades.setdefault(item['trade_id'], []).append(item)
        if item['kind'] == 'signal' and isinstance(item['payload'].get('entry_plan'), dict):
            pivot = item['payload']['entry_plan'].get('pivot')
            if isinstance(pivot, dict):
                pivots.append(dict(time_ns=str(item['stamp']), **pivot))

    for trade_id, items in trades.items():
        plan = _initial_plan(db, trade_id, config, mappings)
        if plan:
            source, start, entry_plan = plan
            stop = decimal_value(entry_plan['stop_price'])
            end = as_of_ns
            for item in items:
                if item['stamp'] > start and (
                        not _quantity(item['risk'])
                        or item['symbol'] != source):
                    end = min(end, item['stamp'])
                    break
            if start <= as_of_ns:
                segments.append(_segment(
                    trade_id, source, 'initial', start, end, stop,
                    _offset(db, mappings, source, start), 0, 0, None))
        for index, item in enumerate(items):
            if (item['kind'] not in ACTIVE_KINDS
                    or not _quantity(item['risk']) or item['stop'] is None):
                continue
            end = as_of_ns
            if index+1 < len(items):
                end = min(end, items[index+1]['stamp'])
            segments.append(_segment(
                trade_id, item['symbol'], 'active', item['stamp'], end, item['stop'],
                _offset(db, mappings, item['symbol'], item['stamp']),
                _quantity(item['risk']), _field(item['risk'], 'stage', 0),
                _field(item['risk'], 'exit_reason')))

    if series == 'actual' and symbol is not None:
        segments = [item for item in segments if item['source_symbol'] == symbol]
        for item in segments:
            item['display_price'] = item['actual_price']
        pivots = []
    return dict(segments=segments, pivots=pivots, truncated=truncated)


def trade_explanation(db, *, fill_key):
    fill = db.execute('SELECT * FROM fills WHERE key=?', (fill_key,)).fetchone()
    if fill is None:
        raise ValueError('成交不存在')
    stamp = fill[7]
    signal = db.execute(
        "SELECT time_ns,payload,risk FROM risk_events WHERE kind='signal' AND time_ns<=? "
        "ORDER BY time_ns DESC,rowid DESC LIMIT 1", (stamp,)).fetchone()
    payload = _payload(signal[1]) if signal else {}
    plan = payload.get('entry_plan', {})
    pivot = plan.get('pivot') if isinstance(plan, dict) else None
    linked = db.execute(
        "SELECT risk FROM risk_events,json_each(risk_events.payload,'$.fill_keys') "
        "WHERE json_each.value=? ORDER BY risk_events.time_ns DESC,risk_events.rowid DESC "
        "LIMIT 1", (fill_key,)).fetchone()
    if linked is None:
        raise ValueError('成交风险关联不完整')
    trade_risk = _risk(linked[0])
    trade_id = _trade_id(trade_risk)
    specs, mappings = _specs(db), _mappings(db)
    events = []
    for row in db.execute(
            "SELECT time_ns,kind,payload,risk FROM risk_events "
            "WHERE json_extract(risk,'$.trade_id')=? ORDER BY time_ns,rowid LIMIT 200",
            (trade_id,)):
        risk = _risk(row[3])
        symbol = (_payload(row[2]).get('symbol')
                  or next((mapping.get('new_symbol') for time_ns, mapping in reversed(mappings)
                           if time_ns <= row[0]), None))
        stop = _stop(risk, specs.get(symbol))
        events.append(dict(time_ns=str(row[0]), kind=row[1],
                           stop_price=str(stop) if stop is not None else None,
                           quantity=_quantity(risk), stage=_field(risk, 'stage', 0),
                           reason=_field(risk, 'exit_reason')))
    initial = db.execute(
        "SELECT risk FROM risk_events WHERE kind='fill' "
        "AND json_extract(risk,'$.trade_id')=? ORDER BY time_ns,rowid LIMIT 1",
        (trade_id,)).fetchone()
    initial_risk = _risk(initial[0]) if initial else trade_risk
    return {
        'fill': dict(zip(
            ('key', 'order_id', 'symbol', 'direction', 'offset', 'volume', 'price', 'time_ns'),
            fill, strict=True)) | {'time_ns': str(fill[7])},
        'trade_id': trade_id,
        'entry_plan': plan,
        'pivot': pivot,
        'initial_r': str(_field(initial_risk, 'initial_r', '')),
        'risk_events': events,
    }
