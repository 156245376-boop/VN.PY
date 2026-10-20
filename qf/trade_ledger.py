"""逐笔逻辑交易账本：从已保存成交、费用和保护证据还原完整交易。"""

import json
import sqlite3
from bisect import bisect_right
from decimal import Decimal

from qf.continuous_journal import logical_from_dict
from qf.continuous_risk import logical_stop
from qf.research_account import account_schema, fill_fee_total
from qf.research_config import decimal_value as dec
from qf.trade_risk import ContractSpec

LIMIT = 500
OPEN_ROLES = {'strategy_open', 'roll_in'}
CLOSE_ROLES = {'strategy_close', 'roll_out'}


def _spec(raw):
    data = dict(raw)
    for key in ('price_tick', 'volume_multiple', 'margin_per_lot', 'commission_per_lot'):
        data[key] = dec(data[key])
    return ContractSpec(**data)


def _payload(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _weighted(fills):
    volume = sum(fill['volume'] for fill in fills)
    if not volume:
        return None
    return sum((dec(fill['price'])*fill['volume'] for fill in fills), Decimal(0))/volume


def _text(value):
    return None if value is None else format(dec(value).normalize(), 'f')


def trade_ledger(db, *, as_of_ns=None, limit=LIMIT):
    """返回按逻辑交易分组的完整证据；缺失关联时明确不可用。"""
    if (as_of_ns is not None and (type(as_of_ns) is not int or as_of_ns < 0)
            or type(limit) is not int or not 1 <= limit <= LIMIT):
        raise ValueError('交易账本范围无效')
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'fills', 'logical_fills', 'logical_trades', 'risk_events',
                'contract_specs'}
    if not required <= tables:
        return dict(available=False, trades=[], fills=[], fee_total=None,
                    fee_reconciled_difference=None, reconciled=False,
                    truncated=False, reason='该结果未保存逐笔交易关联证据。')

    specs = {symbol: _spec(json.loads(raw)) for symbol, raw in db.execute(
        'SELECT symbol,data FROM contract_specs')}
    params = (as_of_ns,) if as_of_ns is not None else ()
    fill_sql = (
        'SELECT l.trade_id,l.symbol,l.role,l.fee,f.key,f.order_id,f.direction,'
        'f.offset,f.volume,f.price,f.time_ns FROM logical_fills l '
        'JOIN fills f ON f.key=l.fill_key')
    if as_of_ns is not None:
        fill_sql += ' WHERE f.time_ns<=?'
    rows = db.execute(fill_sql+' ORDER BY f.time_ns,l.rowid', params).fetchall()
    grouped = {}
    for row in rows:
        values = dict(zip((
            'trade_id', 'symbol', 'role', 'fee', 'key', 'order_id', 'direction',
            'offset', 'volume', 'price', 'time_ns'), row, strict=True))
        values['fee'] = dec(values['fee'])
        grouped.setdefault(values['trade_id'], []).append(values)

    risk_rows = {}
    risk_sql = ('SELECT time_ns,kind,payload,risk FROM risk_events '
                + ('WHERE time_ns<=? ' if as_of_ns is not None else '')
                + 'ORDER BY time_ns,rowid')
    risk_params = (as_of_ns,) if as_of_ns is not None else ()
    for stamp, kind, payload, raw in db.execute(risk_sql, risk_params):
        try:
            risk = logical_from_dict(json.loads(raw))
        except (TypeError, ValueError):
            continue
        if risk.trade_id:
            risk_rows.setdefault(risk.trade_id, []).append(
                dict(time_ns=stamp, kind=kind, payload=_payload(payload), risk=risk))

    close_sql = ('SELECT trade_id,time_ns,reason FROM logical_trades '
                 + ('WHERE time_ns<=?' if as_of_ns is not None else ''))
    closes = {row[0]: dict(trade_id=row[0], time_ns=row[1], reason=row[2])
              for row in db.execute(close_sql, risk_params)}

    signals = [
        dict(time_ns=row[0], payload=_payload(row[1]))
        for row in db.execute(
            'SELECT time_ns,payload FROM risk_events WHERE kind=\'signal\' '
            + ('AND time_ns<=? ' if as_of_ns is not None else '')
            + 'ORDER BY time_ns,rowid', risk_params)
    ]
    signal_times = [item['time_ns'] for item in signals]
    trades = []
    ordered_groups = sorted(grouped.items(), key=lambda pair: min(
        item['time_ns'] for item in pair[1]))
    for trade_id, items in ordered_groups:
        items.sort(key=lambda item: (item['time_ns'], item['key']))
        opens = [item for item in items if item['role'] in OPEN_ROLES]
        closes_for_trade = [item for item in items if item['role'] in CLOSE_ROLES]
        if not opens:
            continue
        first = opens[0]
        signal_idx = bisect_right(signal_times, first['time_ns'])
        plan = signals[signal_idx-1]['payload'].get('entry_plan') if signal_idx else None
        risk_items = risk_rows.get(trade_id, [])
        held = [item['risk'] for item in risk_items if item['risk'].quantity]
        last_risk = held[-1] if held else None
        last_event_risk = risk_items[-1]['risk'] if risk_items else None
        first_risk = next((item['risk'] for item in risk_items
                           if item['risk'].quantity), None)
        initial_stop = plan.get('stop_price') if isinstance(plan, dict) else None
        if initial_stop is None and first_risk is not None:
            spec = specs.get(first['symbol'])
            if spec is not None:
                initial_stop = logical_stop(first_risk, spec=spec)
        final_stop = None
        last_symbol = closes_for_trade[-1]['symbol'] if closes_for_trade else opens[-1]['symbol']
        if last_risk is not None and last_risk.side in (-1, 1):
            last_symbol = opens[-1]['symbol']
            spec = specs.get(last_symbol)
            if spec is not None:
                final_stop = logical_stop(last_risk, spec=spec)
        close = closes.get(trade_id)
        gross = (last_event_risk.realized_gross
                 if last_event_risk is not None else Decimal(0))
        fees = sum((item['fee'] for item in items), Decimal(0))
        quantity = max((risk.quantity for risk in held), default=sum(
            item['volume'] for item in opens))
        initial_opens = [item for item in opens if item['role'] == 'strategy_open']
        final_closes = [item for item in closes_for_trade
                        if item['role'] == 'strategy_close']
        entry_price = _weighted(initial_opens or opens)
        exit_price = _weighted(final_closes or closes_for_trade) if closes_for_trade else None
        status = 'closed' if close is not None else 'open'
        net = gross-fees if close is not None else None
        fill_rows = [dict(
            key=item['key'], order_id=item['order_id'], symbol=item['symbol'],
            role=item['role'], direction=item['direction'], offset=item['offset'],
            volume=item['volume'], price=_text(item['price']),
            time_ns=str(item['time_ns']), fee=_text(item['fee']),
            trade_id=trade_id, trade_status=status,
            trade_net_pnl=_text(net), entry_price=_text(entry_price),
            exit_price=_text(exit_price), initial_stop=_text(initial_stop),
            final_stop=_text(final_stop),
            exit_reason=close['reason'] if close else None)
            for item in items]
        trades.append(dict(
            trade_id=trade_id, status=status, direction=1 if first['direction'] == 'BUY' else -1,
            first_symbol=first['symbol'], last_symbol=last_symbol,
            quantity=quantity, entry_time_ns=str(opens[0]['time_ns']),
            entry_price=_text(entry_price),
            exit_time_ns=str(closes_for_trade[-1]['time_ns']) if closes_for_trade else None,
            exit_price=_text(exit_price),
            initial_stop=_text(initial_stop),
            final_stop=_text(final_stop),
            exit_reason=close['reason'] if close else None,
            gross_pnl=_text(gross), fee=_text(fees),
            net_pnl=_text(net),
            fill_count=len(items), entry_plan=plan if isinstance(plan, dict) else None,
            fills=fill_rows))
    trades.sort(key=lambda item: int(item['entry_time_ns']), reverse=True)
    total = len(trades)
    trades = trades[:limit]
    fills = [fill for trade in trades for fill in trade['fills']]
    try:
        fee_total = _text(fill_fee_total(db)) if account_schema(db) else _text(
            sum((item['fee'] for items in grouped.values() for item in items), Decimal(0)))
        grouped_fees = sum((item['fee'] for items in grouped.values() for item in items),
                           Decimal(0))
        difference = dec(fee_total)-grouped_fees
        reconciled = abs(difference) <= Decimal('0.01')
    except (sqlite3.Error, ValueError):
        fee_total, difference, reconciled = None, None, False
    return dict(available=True, trades=trades, fills=fills, total=total,
                truncated=total > limit, fee_total=fee_total,
                fee_reconciled_difference=_text(difference),
                reconciled=reconciled, reason='')
