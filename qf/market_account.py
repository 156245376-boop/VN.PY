"""当前行情 TqSim 账户的有限业务快照，不创建账户、不返回标识凭证。"""

import math
import re
from collections.abc import Mapping

SUMMARY = ('balance', 'float_profit', 'margin', 'commission', 'available')
NUMBERS = {'pos_long', 'pos_short', 'open_price_long', 'open_price_short', 'float_profit',
           'margin', 'volume_orign', 'volume_left', 'limit_price', 'insert_date_time',
           'volume', 'price', 'trade_date_time'}
FIELDS = {'positions': ('pos_long', 'pos_short', 'open_price_long', 'open_price_short',
                       'float_profit', 'margin'),
          'orders': ('order_id', 'direction', 'offset', 'status', 'volume_orign',
                     'volume_left', 'limit_price', 'insert_date_time'),
          'trades': ('trade_id', 'order_id', 'direction', 'offset', 'volume', 'price',
                     'trade_date_time')}
SYMBOL = re.compile(r'(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{3,4}')


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def public_account(raw):
    if not isinstance(raw, Mapping) or raw.get('kind') != 'local_sim':
        return None
    stamp = raw.get('observed_at')
    summary = raw.get('summary')
    summary = summary if isinstance(summary, Mapping) else {}
    truncated = raw.get('truncated')
    truncated = truncated if isinstance(truncated, Mapping) else {}
    result = {'kind': 'local_sim', 'connected': raw.get('connected') is True,
              'observed_at': stamp if isinstance(stamp, str) and re.fullmatch(
                  r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', stamp) else None,
              'summary': {key: _number(summary.get(key)) for key in SUMMARY},
              'truncated': {}}
    for group, fields in FIELDS.items():
        records = raw.get(group, [])
        records = records if isinstance(records, list) else []
        result['truncated'][group] = (len(records) > 500 or
                                     truncated.get(group) is True)
        result[group] = []
        for row in records[-500:]:
            if not isinstance(row, Mapping) or not isinstance(row.get('symbol'), str) \
                    or not SYMBOL.fullmatch(row['symbol']):
                continue
            clean = {'symbol': row['symbol']}
            for key in fields:
                value = row.get(key)
                if key in NUMBERS:
                    clean[key] = _number(value)
                elif key.endswith('_id'):
                    clean[key] = value if isinstance(value, str) and re.fullmatch(
                        r'[A-Za-z0-9_.:@/-]{1,100}', value) else None
                else:
                    clean[key] = value if value in ('BUY', 'SELL', 'OPEN', 'CLOSE',
                                                   'CLOSETODAY', 'ALIVE', 'FINISHED') else None
            result[group].append(clean)
    return result


def account_snapshot(api, *, connected: bool, observed_at: str) -> dict:
    result = {'kind': 'local_sim', 'connected': connected, 'observed_at': observed_at,
              'summary': api.get_account()}
    for name, method in [('positions', 'get_position'), ('orders', 'get_order'),
                         ('trades', 'get_trade')]:
        rows = []
        for key, row in getattr(api, method)().items():
            if not isinstance(row, Mapping) or str(key).startswith('_'):
                continue
            if name == 'positions' and not (row.get('pos_long') or row.get('pos_short')):
                continue
            symbol = row.get('exchange_id', '') + '.' + row.get('instrument_id', '')
            rows.append({'symbol': symbol, **{field: row.get(field) for field in FIELDS[name]}})
        result[name] = rows
    return public_account(result)
