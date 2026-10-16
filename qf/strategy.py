import math


def completed_signal(rows, period: int):
    """rows 最后一条为形成中柱；返回完成柱时间及目标，不足预热则返回 None。"""
    if len(rows) < period + 1:
        return None
    window = rows[-period - 1:-1]
    times = [int(row["datetime"]) for row in window]
    prices = [float(row["close"]) for row in window]
    if (any(t <= 0 for t in times)
            or any(a >= b for a, b in zip(times, times[1:], strict=False))
            or int(rows[-1]["datetime"]) <= times[-1]
            or not all(math.isfinite(p) and p > 0 for p in prices)):
        return None
    return times[-1], int(prices[-1] > sum(prices) / period)
