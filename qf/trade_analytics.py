"""逐笔交易账本的只读筛选、统计与CSV派生。"""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from qf.research_config import decimal_value as dec

FILTER_KEYS = {'direction', 'status', 'symbol', 'reason', 'start', 'end',
               'min_net', 'max_net'}
DIRECTIONS = {1: '多', -1: '空'}
STATUSES = {'open': '持仓中', 'closed': '已平仓'}
REASONS = {
    'ma_reverse': '反向交叉',
    'initial_stop': '初始止损',
    'stair_stop': '阶梯保护',
    'take_profit': '终点止盈',
    'user_flatten': '用户要求平仓',
    'entry_stop_invalid': '入场即越过止损',
    'strategy_close': '策略平仓',
}
COLUMNS = (
    ('trade_id', '交易编号'), ('status', '状态'), ('first_symbol', '开仓合约'),
    ('last_symbol', '平仓合约'), ('direction', '方向'), ('quantity', '手数'),
    ('entry_time_ns', '开仓时间'), ('entry_price', '开仓均价'),
    ('exit_time_ns', '平仓时间'), ('exit_price', '平仓均价'),
    ('initial_stop', '初始止损'), ('final_stop', '最终保护'),
    ('fee', '手续费（元）'), ('gross_pnl', '毛盈亏（元）'),
    ('net_pnl', '净盈亏（元）'), ('exit_reason', '退出原因'),
)


def _text(value):
    if value is None or value == '':
        return '0'
    value = dec(value).normalize()
    return format(value, 'f')


def _optional_text(value):
    return None if value is None or value == '' else _text(value)


def _date(value, name):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError(f'{name}无效')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{name}无效') from None


def normalize_trade_filters(raw=None):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - FILTER_KEYS:
        raise ValueError('交易筛选字段无效')
    direction = raw.get('direction')
    if direction in (None, '', 'all'):
        direction = None
    elif direction in (1, '1'):
        direction = 1
    elif direction in (-1, '-1'):
        direction = -1
    else:
        raise ValueError('交易方向无效')
    status = raw.get('status')
    if status in (None, '', 'all'):
        status = None
    elif status not in STATUSES:
        raise ValueError('交易状态无效')
    text = {}
    for key in ('symbol', 'reason'):
        value = raw.get(key)
        if value in (None, ''):
            text[key] = None
        elif not isinstance(value, str) or len(value) > 100:
            raise ValueError(f'交易{key}筛选无效')
        else:
            text[key] = value
    start, end = _date(raw.get('start'), '起始日期'), _date(raw.get('end'), '结束日期')
    if start is not None and end is not None and start > end:
        raise ValueError('起始日期不能晚于结束日期')
    amounts = {}
    for key in ('min_net', 'max_net'):
        value = raw.get(key)
        try:
            amounts[key] = None if value in (None, '') else dec(value)
        except ValueError:
            raise ValueError(f'{key}金额无效') from None
    if (amounts['min_net'] is not None and amounts['max_net'] is not None
            and amounts['min_net'] > amounts['max_net']):
        raise ValueError('最小净盈亏不能大于最大净盈亏')
    return {
        'direction': direction, 'status': status,
        'symbol': text['symbol'], 'reason': text['reason'],
        'start': start, 'end': end, **amounts,
    }


def _entry_date(stamp):
    if stamp in (None, ''):
        return None
    try:
        seconds = int(stamp)/1_000_000_000
    except (TypeError, ValueError, OverflowError):
        raise ValueError('交易开仓时间无效') from None
    return datetime.fromtimestamp(seconds, timezone(timedelta(hours=8))).date()


def filter_trades(ledger, filters):
    if not isinstance(ledger, dict) or not isinstance(ledger.get('trades', []), list):
        raise ValueError('交易账本格式无效')
    if not isinstance(filters, dict) or set(filters) != FILTER_KEYS:
        raise ValueError('交易筛选未规范化')
    result = []
    for trade in ledger.get('trades', []):
        if not isinstance(trade, dict):
            raise ValueError('交易账本条目无效')
        if filters['direction'] is not None and trade.get('direction') != filters['direction']:
            continue
        if filters['status'] is not None and trade.get('status') != filters['status']:
            continue
        if filters['symbol'] is not None and filters['symbol'] not in (
                trade.get('first_symbol'), trade.get('last_symbol')):
            continue
        if filters['reason'] is not None and trade.get('exit_reason') != filters['reason']:
            continue
        entry = _entry_date(trade.get('entry_time_ns'))
        if filters['start'] is not None and (entry is None or entry < filters['start']):
            continue
        if filters['end'] is not None and (entry is None or entry > filters['end']):
            continue
        if filters['min_net'] is not None or filters['max_net'] is not None:
            if trade.get('status') != 'closed' or trade.get('net_pnl') in (None, ''):
                continue
            net = dec(trade['net_pnl'])
            if filters['min_net'] is not None and net < filters['min_net']:
                continue
            if filters['max_net'] is not None and net > filters['max_net']:
                continue
        result.append(trade)
    return result


def trade_statistics(trades):
    if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
        raise ValueError('交易统计输入无效')
    closed = [item for item in trades if item.get('status') == 'closed']
    nets = [dec(item['net_pnl']) for item in closed
            if item.get('net_pnl') not in (None, '')]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    flat = [value for value in nets if value == 0]
    gains = sum(wins, Decimal(0))
    losses_total = sum(losses, Decimal(0))
    rated = len(wins)+len(losses)+len(flat)
    win_rate = (Decimal(len(wins))*100/rated) if rated else Decimal(0)
    gross = sum((dec(item.get('gross_pnl') or 0) for item in trades), Decimal(0))
    fees = sum((dec(item.get('fee') or 0) for item in trades), Decimal(0))
    return {
        'count': len(trades),
        'closed_count': len(closed),
        'open_count': len(trades)-len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'flat': len(flat),
        'win_rate': _text(win_rate),
        'gross_pnl': _text(gross),
        'fee': _text(fees),
        'net_pnl': _text(sum(nets, Decimal(0))),
        'average_win': _text(gains/len(wins) if wins else 0),
        'average_loss': _text(losses_total/len(losses) if losses else 0),
        'max_win': _text(max(wins) if wins else 0),
        'max_loss': _text(min(losses) if losses else 0),
    }


def _time_text(stamp):
    if stamp in (None, ''):
        return ''
    try:
        seconds = int(stamp)/1_000_000_000
    except (TypeError, ValueError, OverflowError):
        return ''
    return datetime.fromtimestamp(seconds, timezone(timedelta(hours=8))).isoformat(
        sep=' ', timespec='seconds')


def _csv_value(key, value):
    if key == 'status':
        return STATUSES.get(value, value or '')
    if key == 'direction':
        return DIRECTIONS.get(value, value)
    if key in {'entry_time_ns', 'exit_time_ns'}:
        return _time_text(value)
    if key == 'exit_reason':
        return REASONS.get(value, value or '')
    return '' if value is None else value


def trade_ledger_csv(trades):
    if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
        raise ValueError('交易CSV输入无效')
    output = io.StringIO(newline='')
    output.write('\ufeff')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow([label for _, label in COLUMNS])
    for trade in trades:
        writer.writerow([_csv_value(key, trade.get(key)) for key, _ in COLUMNS])
    return output.getvalue()
