"""复用 MarketProfile；在整数跳数域归集，避免浮点 ceil 错分档。"""

import math
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
from market_profile import MarketProfile

from qf.indicator_catalog import number


def calculate_volume_profile(rows: list[dict], settings: dict, price_tick: float) -> dict:
    number(price_tick, 1e-10, 1e10)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('VP 输入须为 1–20000 根柱')
    prices, volumes = [], []
    tick = Decimal(str(price_tick))
    for row in rows:
        number(row.get('close'), 0, 1e12)
        number(row.get('volume'), 0, 1e15)
        if row['volume']:
            prices.append(int((Decimal(str(row['close'])) / tick).to_integral_value(
                rounding=ROUND_HALF_UP)))
            volumes.append(row['volume'])
    if not volumes:
        raise ValueError('所选范围没有有效成交量')
    step = number(settings.get('ticks_per_row', 0), 0, 10000, integer=True)
    step = step or max(1, math.ceil((max(prices)-min(prices)+1)/64))
    first, last = -(-min(prices)//step), -(-max(prices)//step)
    if last-first+1 > 512:
        raise ValueError('价格档超过 512，请增大每档跳数')
    frame = pd.DataFrame({'Close': prices, 'Volume': volumes})
    profile = MarketProfile(frame, row_size=step, tick_size=1)[:]
    bins = []
    total = float(profile.total_volume)
    for i in range(first, last+1):
        upper = i*step
        volume = float(profile.profile.get(upper, 0))
        bins.append({'low': float(Decimal(upper-step)*tick),
                     'high': float(Decimal(upper)*tick), 'volume': volume,
                     'share': volume/total})
    return {'bins': bins, 'total_volume': total,
            'poc': float(Decimal(str(profile.poc_price))*tick), 'ticks_per_row': step,
            'method': '按收盘价归集', 'estimate': True}
