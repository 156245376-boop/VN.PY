"""单次回测引擎(CPU,逻辑权威版)。

采用逐根 K 线的事件推进:信号在第 i 根生成,第 i+1 根按收盘价换仓,
避免未来函数。绩效统计口径与向量化矩阵引擎保持一致,便于对拍验证。
"""
from __future__ import annotations

import numpy as np

from app.models.schemas import (
    Bar,
    BacktestRequest,
    BacktestResult,
    BacktestStats,
    EventFilter,
    TimeOfDayFilter,
)
from app.services import data_service, event_service, strategies


def _apply_filters(
    bars: list[Bar], time_filter: TimeOfDayFilter, event_filter: EventFilter
) -> np.ndarray:
    """返回布尔掩码:True 表示该根 K 线参与交易(未被过滤)。"""
    n = len(bars)
    mask = np.ones(n, dtype=bool)
    intervals = event_service.get_event_intervals(event_filter)
    for i, bar in enumerate(bars):
        if not event_service.passes_time_filter(bar.ts, time_filter):
            mask[i] = False
            continue
        if intervals:
            inside = event_service.in_any_interval(bar.ts, intervals)
            if event_filter.mode == "exclude" and inside:
                mask[i] = False
            elif event_filter.mode == "only" and not inside:
                mask[i] = False
    return mask


def compute_stats(
    equity: np.ndarray, position: np.ndarray, bars_per_year: float
) -> BacktestStats:
    """统一绩效统计:总收益、年化、最大回撤、夏普、交易次数、胜率。"""
    equity = np.asarray(equity, dtype=float)
    if len(equity) < 2:
        return BacktestStats(
            total_return=0.0, annual_return=0.0, max_drawdown=0.0,
            sharpe=0.0, trade_count=0, win_rate=0.0, final_equity=float(equity[-1] if len(equity) else 0.0),
        )
    start_eq = equity[0]
    total_return = float(equity[-1] / start_eq - 1.0)
    step_returns = np.diff(equity) / equity[:-1]
    n = len(step_returns)
    ann = float((equity[-1] / start_eq) ** (bars_per_year / max(n, 1)) - 1.0) if equity[-1] > 0 else -1.0
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_dd = float(drawdown.min())
    std = step_returns.std()
    sharpe = float(step_returns.mean() / std * np.sqrt(bars_per_year)) if std > 0 else 0.0
    # 交易次数:持仓方向变化次数;胜率:换仓区间收益为正的比例。
    pos = np.asarray(position, dtype=float)
    changes = np.where(np.diff(pos) != 0)[0]
    trade_count = int(len(changes))
    win_rate = 0.0
    if trade_count > 0:
        seg_starts = np.concatenate(([0], changes + 1))
        seg_ends = np.concatenate((changes + 1, [len(equity) - 1]))
        wins = 0
        segs = 0
        for s, e in zip(seg_starts, seg_ends):
            if e > s and equity[s] > 0:
                segs += 1
                if equity[e] > equity[s]:
                    wins += 1
        win_rate = float(wins / segs) if segs else 0.0
    return BacktestStats(
        total_return=total_return,
        annual_return=ann,
        max_drawdown=max_dd,
        sharpe=sharpe,
        trade_count=trade_count,
        win_rate=win_rate,
        final_equity=float(equity[-1]),
    )


def _bars_per_year(interval: str) -> float:
    from app.models.schemas import INTERVAL_SECONDS

    sec = INTERVAL_SECONDS.get(interval, 60)
    # 国内期货约 250 交易日、每日约 4 小时连续交易估算。
    trading_seconds_per_year = 250 * 4 * 3600
    return trading_seconds_per_year / sec


def run_backtest(req: BacktestRequest) -> BacktestResult:
    """执行单次回测(CPU 事件推进)。"""
    bars = data_service.get_bars(req.symbol, req.interval, req.start, req.end, limit=0 or 10_000_000)
    if len(bars) < 2:
        raise ValueError("数据不足,无法回测(至少需要 2 根 K 线)")
    closes = np.array([b.close for b in bars], dtype=float)
    params = req.params or {p.name: p.default for p in strategies.STRATEGIES[req.strategy].params}
    raw_signal = strategies.generate_signal(req.strategy, closes, params)
    trade_mask = _apply_filters(bars, req.time_filter, req.event_filter)

    equity = np.empty(len(bars), dtype=float)
    equity[0] = req.capital
    position = np.zeros(len(bars), dtype=float)
    cur_pos = 0.0
    for i in range(1, len(bars)):
        # 用上一根生成的信号在本根换仓,受过滤掩码约束。
        desired = raw_signal[i - 1] if trade_mask[i - 1] else 0.0
        cur_pos = desired
        position[i] = cur_pos
        ret = (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] else 0.0
        equity[i] = equity[i - 1] * (1.0 + cur_pos * ret)
    stats = compute_stats(equity, position, _bars_per_year(req.interval))
    curve = [
        {"ts": bars[i].ts, "equity": round(float(equity[i]), 2)}
        for i in range(0, len(bars), max(1, len(bars) // 500))
    ]
    if curve and curve[-1]["ts"] != bars[-1].ts:
        curve.append({"ts": bars[-1].ts, "equity": round(float(equity[-1]), 2)})
    return BacktestResult(stats=stats, equity_curve=curve, backend="cpu")
