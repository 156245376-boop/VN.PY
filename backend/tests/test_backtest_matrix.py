"""回测与场景矩阵的正确性对拍。

核心保证:场景矩阵的向量化回测,与单次事件回测在同一组参数/过滤条件下,
总收益、期末权益等指标一致。这样 GPU 批量结果才可信。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from app.models.schemas import (
    BacktestRequest,
    Bar,
    EventFilter,
    MatrixRequest,
    TimeOfDayFilter,
)
from app.services import backtest_service, data_service, matrix_service


def _seed_prices(symbol: str, n: int = 300) -> None:
    """写入一段带趋势与波动的 1m K 线,便于产生交易。"""
    base = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    rng = np.random.default_rng(42)
    price = 3000.0
    bars = []
    for i in range(n):
        price *= 1.0 + rng.normal(0, 0.002) + 0.0003 * math.sin(i / 10)
        p = round(price, 1)
        bars.append(Bar(ts=base + i * 60, open=p, high=p + 2, low=p - 2, close=p, volume=1))
    data_service._upsert_bars(symbol, bars)


def test_matrix_matches_single_backtest(db):
    _seed_prices("rb0", 300)
    params = {"fast": 5, "slow": 20}

    single = backtest_service.run_backtest(
        BacktestRequest(symbol="rb0", interval="1m", strategy="double_ma", params=params)
    )

    matrix = matrix_service.run_matrix(
        MatrixRequest(
            symbols=["rb0"],
            intervals=["1m"],
            strategy="double_ma",
            param_grid={"fast": [5], "slow": [20]},
            prefer_gpu=False,
        )
    )
    assert len(matrix.cells) == 1
    cell = matrix.cells[0]
    # 总收益与期末权益应高度一致(浮点容差)。
    assert abs(cell.stats.total_return - single.stats.total_return) < 1e-6
    assert abs(cell.stats.final_equity - single.stats.final_equity) < 1e-3


def test_matrix_expands_all_combos(db):
    _seed_prices("rb0", 200)
    _seed_prices("ag0", 200)
    matrix = matrix_service.run_matrix(
        MatrixRequest(
            symbols=["rb0", "ag0"],
            intervals=["1m", "5m"],
            strategy="double_ma",
            param_grid={"fast": [5, 10], "slow": [20, 40]},
            time_filters=[TimeOfDayFilter(), TimeOfDayFilter(skip_open_minutes=15)],
            event_filters=[EventFilter()],
            prefer_gpu=False,
        )
    )
    # 2 品种 × 2 周期 × 4 参数组合 × 2 时段 × 1 事件 = 32
    assert matrix.combo_count == 32
    assert matrix.backend == "cpu"


def test_event_exclusion_changes_result(db):
    _seed_prices("rb0", 300)
    from app.services import event_service
    from app.models.schemas import EventItem

    base = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    # 覆盖中间一段的事件区间。
    event_service.add_event(
        EventItem(label="test", category="macro", start_ts=base + 100 * 60, end_ts=base + 200 * 60)
    )
    no_filter = backtest_service.run_backtest(
        BacktestRequest(symbol="rb0", strategy="double_ma", params={"fast": 5, "slow": 20})
    )
    excluded = backtest_service.run_backtest(
        BacktestRequest(
            symbol="rb0",
            strategy="double_ma",
            params={"fast": 5, "slow": 20},
            event_filter=EventFilter(mode="exclude", categories=["macro"]),
        )
    )
    # 排除事件区间后结果应发生变化。
    assert no_filter.stats.final_equity != excluded.stats.final_equity
