"""策略定义与信号生成。

策略以「参数 + K 线序列 -> 目标持仓信号(-1/0/1)」的纯函数形式表达,
既可用于 CPU 单次事件回测,也可用于向量化批量回测(场景矩阵)。
"""
from __future__ import annotations

import numpy as np

from app.models.schemas import StrategyInfo, StrategyParam

STRATEGIES: dict[str, StrategyInfo] = {
    "double_ma": StrategyInfo(
        key="double_ma",
        name="双均线",
        description="快线上穿慢线做多,下穿做空。",
        params=[
            StrategyParam(name="fast", default=10, min=2, max=60, step=1),
            StrategyParam(name="slow", default=30, min=5, max=200, step=1),
        ],
    ),
    "rsi_reversion": StrategyInfo(
        key="rsi_reversion",
        name="RSI 均值回归",
        description="RSI 低于下阈值做多,高于上阈值做空。",
        params=[
            StrategyParam(name="period", default=14, min=2, max=60, step=1),
            StrategyParam(name="low", default=30, min=5, max=45, step=1),
            StrategyParam(name="high", default=70, min=55, max=95, step=1),
        ],
    ),
}


def list_strategies() -> list[StrategyInfo]:
    return list(STRATEGIES.values())


def _sma(values: np.ndarray, window: int) -> np.ndarray:
    window = max(1, int(window))
    if window <= 1:
        return values.copy()
    kernel = np.ones(window) / window
    out = np.convolve(values, kernel, mode="full")[: len(values)]
    # 前 window-1 个点用累计均值填充,避免边界失真过大。
    for i in range(min(window - 1, len(values))):
        out[i] = values[: i + 1].mean()
    return out


def _rsi(values: np.ndarray, period: int) -> np.ndarray:
    period = max(2, int(period))
    delta = np.diff(values, prepend=values[0])
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    avg_gain = _sma(gain, period)
    avg_loss = _sma(loss, period)
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))
    rsi[avg_loss == 0] = 100
    return rsi


def generate_signal(strategy: str, closes: np.ndarray, params: dict[str, float]) -> np.ndarray:
    """返回与 closes 等长的目标持仓数组(-1/0/1)。

    信号在当根 K 线生成,回测时以下一根开盘/收盘执行,避免未来函数。
    """
    if strategy == "double_ma":
        fast = int(params.get("fast", 10))
        slow = int(params.get("slow", 30))
        fast_ma = _sma(closes, fast)
        slow_ma = _sma(closes, slow)
        signal = np.where(fast_ma > slow_ma, 1.0, -1.0)
        return signal
    if strategy == "rsi_reversion":
        period = int(params.get("period", 14))
        low = float(params.get("low", 30))
        high = float(params.get("high", 70))
        rsi = _rsi(closes, period)
        signal = np.zeros_like(closes)
        signal[rsi < low] = 1.0
        signal[rsi > high] = -1.0
        # 持仓延续到反向信号出现。
        for i in range(1, len(signal)):
            if signal[i] == 0:
                signal[i] = signal[i - 1]
        return signal
    raise ValueError(f"未知策略: {strategy}")
