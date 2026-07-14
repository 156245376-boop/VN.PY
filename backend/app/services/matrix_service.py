"""场景矩阵引擎(核心)。

把「多品种 × 多周期 × 时段过滤 × 事件过滤 × 参数网格」展开为大批量回测组合,
用向量化方式在 CPU(NumPy)或 GPU(CuPy)上并行执行。对同一组参数/过滤条件,
其绩效结果与 backtest_service 的 CPU 事件回测保持一致(见 tests 对拍)。

向量化思路:对每个 (品种, 周期, 过滤组合),先算出一次 close 序列与掩码;再把
该品种下所有参数组合堆叠成矩阵,一次性算出每个组合的逐 bar 收益与净值曲线,
批量输出绩效统计。GPU 不可用时自动回落 NumPy。
"""
from __future__ import annotations

import itertools
import time
from typing import Any

import numpy as np

from app.core.compute import get_backend, to_numpy
from app.models.schemas import (
    Bar,
    EventFilter,
    MatrixCell,
    MatrixRequest,
    MatrixResult,
    TimeOfDayFilter,
)
from app.services import backtest_service, data_service, event_service, strategies


def _expand_param_grid(param_grid: dict[str, list[float]]) -> list[dict[str, float]]:
    """笛卡尔展开参数网格。空网格时返回单个空组合(用策略默认值)。"""
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    combos = []
    for values in itertools.product(*[param_grid[k] for k in keys]):
        combos.append(dict(zip(keys, values)))
    return combos


def _signal_matrix(
    strategy: str, closes: np.ndarray, param_combos: list[dict[str, float]]
) -> np.ndarray:
    """为一组参数组合生成信号矩阵,形状 (组合数, bar 数)。"""
    rows = [strategies.generate_signal(strategy, closes, p) for p in param_combos]
    return np.vstack(rows) if rows else np.empty((0, len(closes)))


def _vectorized_stats(
    xp: Any,
    closes_x: Any,
    signal_x: Any,
    trade_mask_x: Any,
    capital: float,
    bars_per_year: float,
) -> list[dict[str, float]]:
    """在选定后端上批量计算每个参数组合的绩效。

    signal_x 形状 (组合数, bar 数)。返回与组合数等长的统计字典列表。
    """
    n_combo, n_bar = signal_x.shape
    if n_bar < 2:
        return [
            {"total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
             "sharpe": 0.0, "trade_count": 0, "win_rate": 0.0, "final_equity": capital}
            for _ in range(n_combo)
        ]
    # 逐 bar 简单收益,shape (bar-1,)
    rets = (closes_x[1:] - closes_x[:-1]) / closes_x[:-1]
    rets = xp.nan_to_num(rets)
    # 本根持仓 = 上一根信号 × 上一根掩码;对齐到 rets(第 i 根收益用 position[i])。
    eff_signal = signal_x * trade_mask_x[xp.newaxis, :]
    position = eff_signal[:, :-1]  # shape (combo, bar-1)
    port_rets = position * rets[xp.newaxis, :]
    growth = 1.0 + port_rets
    equity = capital * xp.cumprod(growth, axis=1)
    # 前置起始资金列
    start_col = xp.full((n_combo, 1), capital)
    equity = xp.concatenate([start_col, equity], axis=1)  # shape (combo, bar)

    total_return = equity[:, -1] / capital - 1.0
    running_max = xp.maximum.accumulate(equity, axis=1)
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min(axis=1)
    step_mean = port_rets.mean(axis=1)
    step_std = port_rets.std(axis=1)
    sharpe = xp.where(step_std > 0, step_mean / xp.where(step_std > 0, step_std, 1) * xp.sqrt(bars_per_year), 0.0)
    exp = bars_per_year / max(n_bar - 1, 1)
    safe_final = xp.where(equity[:, -1] > 0, equity[:, -1], capital * 1e-9)
    annual = (safe_final / capital) ** exp - 1.0
    # 交易次数:position 沿 bar 轴变化次数
    pos_change = xp.abs(xp.diff(position, axis=1)) > 1e-12
    trade_count = pos_change.sum(axis=1)

    tr = to_numpy(total_return)
    dd = to_numpy(max_dd)
    sh = to_numpy(sharpe)
    an = to_numpy(annual)
    tc = to_numpy(trade_count)
    fe = to_numpy(equity[:, -1])
    # 胜率在向量化下用近似:盈利 bar 占持仓 bar 比例(与事件版口径不同,仅作参考)。
    pos_np = to_numpy(position)
    ret_np = to_numpy(rets)
    out = []
    for i in range(n_combo):
        held = pos_np[i] != 0
        if held.any():
            seg_ret = pos_np[i][held] * ret_np[held]
            win_rate = float((seg_ret > 0).mean())
        else:
            win_rate = 0.0
        out.append({
            "total_return": float(tr[i]),
            "annual_return": float(an[i]),
            "max_drawdown": float(dd[i]),
            "sharpe": float(sh[i]),
            "trade_count": int(tc[i]),
            "win_rate": win_rate,
            "final_equity": float(fe[i]),
        })
    return out


def run_matrix(req: MatrixRequest) -> MatrixResult:
    """展开并执行场景矩阵。"""
    t0 = time.perf_counter()
    xp, backend = get_backend(req.prefer_gpu)
    param_combos = _expand_param_grid(req.param_grid)
    cells: list[MatrixCell] = []

    for symbol in req.symbols:
        for interval in req.intervals:
            bars = data_service.get_bars(symbol, interval, req.start, req.end, limit=10_000_000)
            if len(bars) < 2:
                continue
            closes = np.array([b.close for b in bars], dtype=float)
            bpy = backtest_service._bars_per_year(interval)
            signal_full = _signal_matrix(req.strategy, closes, param_combos)
            closes_x = xp.asarray(closes)
            signal_x = xp.asarray(signal_full)
            for tf in req.time_filters:
                for ef in req.event_filters:
                    mask = backtest_service._apply_filters(bars, tf, ef).astype(float)
                    mask_x = xp.asarray(mask)
                    stats_list = _vectorized_stats(
                        xp, closes_x, signal_x, mask_x, req.capital, bpy
                    )
                    for combo, st in zip(param_combos, stats_list):
                        cells.append(
                            MatrixCell(
                                symbol=symbol,
                                interval=interval,
                                params=combo,
                                time_filter=tf.model_dump(),
                                event_filter=ef.model_dump(),
                                stats=st,  # type: ignore[arg-type]
                            )
                        )
    elapsed = (time.perf_counter() - t0) * 1000
    return MatrixResult(
        cells=cells,
        backend=backend,
        elapsed_ms=round(elapsed, 1),
        combo_count=len(cells),
    )
