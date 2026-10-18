"""面向显示的纯计算；无认证、无 TqApi、无交易操作。"""

import math
import re

import pandas as pd
from tqsdk import ta

from qf.indicator_catalog import CATALOG, number, validate_item
from qf.volume_profile import calculate_volume_profile

ROW_KEYS = {'id', 'time_ns', 'open', 'high', 'low', 'close', 'volume', 'close_oi'}


def validate_rows(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('输入须为 1–20000 根柱')
    previous = None
    for row in rows:
        if (not isinstance(row, dict) or set(row) != ROW_KEYS
                or not isinstance(row['time_ns'], str)
                or not re.fullmatch(r'\d{16,20}', row['time_ns'])):
            raise ValueError('指标输入柱字段无效')
        number(row['id'], 0, 2**53-1, integer=True)
        for key in ROW_KEYS-{'id', 'time_ns'}:
            number(row[key], 0, 1e15)
        if (row['low'] > min(row['open'], row['close'], row['high'])
                or row['high'] < max(row['open'], row['close'], row['low'])
                or previous and (row['id'] != previous['id']+1
                                 or int(row['time_ns']) <= int(previous['time_ns']))):
            raise ValueError('指标输入存在坏柱、缺柱或时间倒序')
        previous = row
    return rows


def calculate_indicators(request: dict) -> dict:
    rows = validate_rows(request['rows'])
    items = [validate_item(i) for i in request['items']]
    frame = pd.DataFrame(rows)
    result = {'series': [], 'profiles': [], 'issues': [],
              'calculation_start_ns': rows[0]['time_ns'],
              'warmup': '按实际已加载数据计算；首段可能不足预热；OBV 从该起点累计'}
    for item in items:
        if not item['visible']:
            continue
        kind, p = item['type'], item['params']
        try:
            if kind == 'vp':
                wanted = p['range'] if p['mode'] == 'fixed' else None
                if p['mode'] == 'fixed' and (not wanted or wanted['symbol'] != request['symbol']):
                    raise ValueError('请为本合约重新选择 VP 区间')
                selected = [r for r in rows if (int(wanted['start_ns']) <= int(r['time_ns'])
                            < int(wanted['end_ns']))] if wanted else [
                                r for r in rows if
                                request['visible'][0] <= r['id'] <= request['visible'][1]]
                if not selected:
                    raise ValueError('所选范围尚未完整加载')
                end = int(rows[-1]['time_ns'])+60_000_000_000
                if wanted and (int(wanted['start_ns']) < int(rows[0]['time_ns'])
                               or int(wanted['end_ns']) > request.get('coverage_end_ns', end)):
                    raise ValueError('所选范围尚未完整加载')
                value = calculate_volume_profile(selected, p, request['price_tick'])
                result['profiles'].append({'item_id': item['id'], 'period': request['period'],
                    'start_ns': selected[0]['time_ns'], 'end_ns': selected[-1]['time_ns'], **value})
                continue
            if kind in ('volume', 'oi'):
                output = pd.DataFrame({kind: frame['volume' if kind == 'volume' else 'close_oi']})
            elif kind in ('ma', 'ema'):
                output = pd.DataFrame({str(n): getattr(ta, kind.upper())(frame, n).iloc[:, 0]
                                       for n in p['periods']})
            else:
                output = getattr(ta, kind.upper())(frame, *(p[k] for k in CATALOG[kind][2]))
            for name in output.columns:
                result['series'].append({'item_id': item['id'], 'name': str(name),
                    'board': CATALOG[kind][1], 'unit': '手' if kind in ('volume', 'oi', 'obv')
                    else '价格' if kind in ('ma', 'ema', 'boll', 'sar', 'atr', 'macd')
                    else '指标值',
                    'points': [{'id': row['id'], 'time_ns': row['time_ns'],
                        'value': float(v) if math.isfinite(float(v)) else None}
                        for row, v in zip(rows, output[name], strict=True)]})
        except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError):
            result['issues'].append({'item_id': item['id'], 'reason':
                '指标数据不足或参数不适用；VP 请检查区间、成交量和价格分档'})
    return result
