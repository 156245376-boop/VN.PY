import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from tqsdk import ta

from qf.indicator_calculation import calculate_indicators
from qf.indicator_catalog import default_item


def bars(count=160):
    return [dict(id=i, time_ns=str(1_700_000_000_000_000_000+i*60_000_000_000),
                 open=100+i*.1, high=102+i*.1, low=98+i*.1,
                 close=100+math.sin(i)*2+i*.1, volume=i+1, close_oi=100+i)
            for i in range(count)]


def request(rows, items):
    return dict(rows=rows, items=items, price_tick=.2, symbol='SHFE.rb2701',
                period='1m', visible=[rows[0]['id'], rows[-1]['id']])


def test_ma_is_simple_not_sdk_sma():
    rows = bars(4)
    for row, value in zip(rows, [1, 2, 3, 4], strict=True):
        row.update(open=value, high=value, low=value, close=value)
    item = default_item('ma')
    item['params']['periods'] = [3]
    result = calculate_indicators(request(rows, [item]))
    assert [p['value'] for p in result['series'][0]['points']] == [None, None, 2, 3]


@pytest.mark.parametrize('kind,args', [
    ('ema', (12,)), ('boll', (20, 2)), ('sar', (4, .02, .2)),
    ('macd', (12, 26, 9)), ('kdj', (9, 3, 3)), ('rsi', (6,)),
    ('atr', (14,)), ('cci', (14,)), ('dmi', (14, 6)), ('obv', ()),
])
def test_official_indicator_parity(kind, args):
    rows = bars()
    item = default_item(kind)
    if kind == 'ema':
        item['params']['periods'] = [12]
    result = calculate_indicators(request(rows, [item]))
    frame = pd.DataFrame(rows)
    expected = getattr(ta, kind.upper())(frame, *args)
    assert not result['issues']
    for series, name in zip(result['series'], expected.columns, strict=True):
        actual = [p['value'] for p in series['points']]
        wanted = [float(v) if math.isfinite(float(v)) else None for v in expected[name]]
        assert actual == wanted


def test_flat_or_missing_data_does_not_fabricate_zero():
    rows = bars(10)
    result = calculate_indicators(request(rows, [default_item('ma')]))
    assert result['series'][0]['points'][0]['value'] is None
    rows[3]['volume'] = -1
    with pytest.raises(ValueError):
        calculate_indicators(request(rows, [default_item('ma')]))


def test_parameter_key_order_cannot_change_formula():
    rows = bars()
    item = default_item('macd')
    original = calculate_indicators(request(rows, [item]))
    item['params'] = {'m': 9, 'long': 26, 'short': 12}
    assert calculate_indicators(request(rows, [item])) == original


def test_fixed_profile_uses_full_loaded_intervals_and_isolates_missing_range():
    rows = bars(4)
    vp = default_item('vp', 'vp-fixed')
    vp['params'].update(mode='fixed', range={'symbol': 'SHFE.rb2701',
        'start_ns': rows[0]['time_ns'],
        'end_ns': str(int(rows[1]['time_ns'])+60_000_000_000)})
    data = request(rows, [vp, default_item('ma')])
    data['coverage_end_ns'] = str(int(rows[-1]['time_ns'])+60_000_000_000)
    result = calculate_indicators(data)
    assert result['profiles'][0]['total_volume'] == 3
    vp['params']['range']['end_ns'] = str(int(data['coverage_end_ns'])+60_000_000_000)
    result = calculate_indicators(data)
    assert not result['profiles'] and result['issues']
    assert result['series'], '固定区间缺失不能停止其他指标'


def test_monday_daily_bar_includes_friday_night_range():
    def stamp(day, hour):
        return str(int(datetime(2026, 10, day, hour, tzinfo=timezone(
            timedelta(hours=8))).timestamp())*1_000_000_000)
    rows = bars(1)
    rows[0]['time_ns'] = stamp(19, 0)
    vp = default_item('vp', 'vp-fixed')
    vp['params'].update(mode='fixed', range={'symbol': 'SHFE.rb2701',
                                           'start_ns': stamp(16, 21),
                                           'end_ns': stamp(17, 2)})
    data = request(rows, [vp]) | {'period': '1d', 'coverage_end_ns': stamp(19, 18)}
    assert calculate_indicators(data)['profiles'][0]['total_volume'] == 1
