"""双均线完成柱交叉；不读取账户、不执行委托。"""

import math
from dataclasses import dataclass

import pandas as pd
from tqsdk.tafunc import ma


@dataclass(frozen=True)
class CrossSignal:
    bar_start_ns: int
    completed_ns: int
    direction: int
    fast_previous: float
    slow_previous: float
    fast_current: float
    slow_current: float


def completed_cross(rows, fast, slow, *, completed_ns):
    if (type(fast) is not int or type(slow) is not int or not 2 <= fast < slow <= 200
            or len(rows) < slow + 2 or type(completed_ns) is not int):
        return None
    try:
        window = rows[-slow-2:]
        times = [int(r['datetime']) for r in window]
        prices = [float(r['close']) for r in window[:-1]]
        if (any(t <= 0 for t in times) or completed_ns < times[-1]
                or any(a >= b for a, b in zip(times, times[1:], strict=False))
                or any(not math.isfinite(p) or p <= 0 for p in prices)):
            return None
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    values = pd.Series(prices)
    f, s = ma(values, fast), ma(values, slow)
    previous, current = f.iloc[-2]-s.iloc[-2], f.iloc[-1]-s.iloc[-1]
    direction = 1 if previous <= 0 < current else -1 if previous >= 0 > current else 0
    return (CrossSignal(times[-2], completed_ns, direction, float(f.iloc[-2]),
                        float(s.iloc[-2]), float(f.iloc[-1]), float(s.iloc[-1]))
            if direction else None)
