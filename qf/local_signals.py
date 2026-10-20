"""本地双均线信号；只消费已完成柱，不构造未来数据。"""

import pandas as pd


def ma_cross_signals(frame, *, fast, slow, bar_seconds):
    if (not isinstance(frame, pd.DataFrame)
            or not {'time_ns', 'close', 'completed'} <= set(frame.columns)):
        raise ValueError('本地K线字段不完整')
    if (type(fast) is not int or type(slow) is not int
            or fast < 1 or slow < 1 or fast >= slow):
        raise ValueError('均线周期无效')
    if type(bar_seconds) is not int or bar_seconds < 1:
        raise ValueError('K线周期无效')
    stamps = pd.to_numeric(frame['time_ns'], errors='raise').astype('int64')
    if stamps.duplicated().any() or not stamps.is_monotonic_increasing:
        raise ValueError('K线时间重复或倒序')
    values = frame.copy()
    values['_source_index'] = values.index
    values['_time_ns'] = stamps
    completed = values[values['completed'].astype(bool)].copy()
    if len(completed) < slow+1:
        return []
    closes = pd.to_numeric(completed['close'], errors='raise').astype(float)
    fast_ma = closes.rolling(fast, min_periods=fast).mean()
    slow_ma = closes.rolling(slow, min_periods=slow).mean()
    previous_fast, previous_slow = fast_ma.shift(1), slow_ma.shift(1)
    above = (fast_ma > slow_ma) & (previous_fast <= previous_slow)
    below = (fast_ma < slow_ma) & (previous_fast >= previous_slow)
    signals = []
    for position in range(len(completed)):
        if not above.iloc[position] and not below.iloc[position]:
            continue
        row = completed.iloc[position]
        completed_ns = int(row.get('completed_ns', row['_time_ns']+bar_seconds*1_000_000_000))
        signals.append({
            'bar_index': int(row['_source_index']),
            'time_ns': str(int(row['_time_ns'])),
            'completed_ns': str(completed_ns),
            'direction': 1 if above.iloc[position] else -1,
            'fast_previous': float(previous_fast.iloc[position]),
            'slow_previous': float(previous_slow.iloc[position]),
            'fast_current': float(fast_ma.iloc[position]),
            'slow_current': float(slow_ma.iloc[position]),
            'close': float(row['close']),
            'symbol': row.get('symbol'),
        })
    return signals
