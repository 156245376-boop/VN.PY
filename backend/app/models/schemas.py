"""跨服务共享的 Pydantic 模型与常量。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 支持的周期。基础存储周期为 1m,其余由重采样合成。
INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"]
# 每个周期对应的秒数(1d 特殊,按自然日归组)。
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "1d": 86400,
}


class Bar(BaseModel):
    """一根 K 线。"""

    ts: int  # Unix 秒
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class SymbolInfo(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    bar_count: int = 0
    first_ts: int | None = None
    last_ts: int | None = None


class DownloadRequest(BaseModel):
    symbol: str = Field(..., description="合约代码,如 rb2410 或 rb 主连")
    start: str = Field(..., description="开始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    interval: str = Field("1m", description="下载周期,默认 1m")


class BarsQuery(BaseModel):
    symbol: str
    interval: str = "1m"
    start: str | None = None
    end: str | None = None
    limit: int = 5000


class EventItem(BaseModel):
    id: int | None = None
    label: str
    category: str = "macro"
    start_ts: int
    end_ts: int
    symbol: str | None = None
    source: str = "manual"
    note: str | None = None


class TimeOfDayFilter(BaseModel):
    """时段过滤:排除开盘后 / 收盘前若干分钟。"""

    skip_open_minutes: int = 0
    skip_close_minutes: int = 0


class EventFilter(BaseModel):
    """事件过滤:排除或仅保留某些分类的事件区间。"""

    mode: Literal["none", "exclude", "only"] = "none"
    categories: list[str] = Field(default_factory=list)


class StrategyParam(BaseModel):
    name: str
    default: float
    min: float
    max: float
    step: float


class StrategyInfo(BaseModel):
    key: str
    name: str
    description: str
    params: list[StrategyParam]


class BacktestRequest(BaseModel):
    symbol: str
    interval: str = "1m"
    strategy: str = "double_ma"
    params: dict[str, float] = Field(default_factory=dict)
    start: str | None = None
    end: str | None = None
    capital: float = 1_000_000.0
    time_filter: TimeOfDayFilter = Field(default_factory=TimeOfDayFilter)
    event_filter: EventFilter = Field(default_factory=EventFilter)


class BacktestStats(BaseModel):
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe: float
    trade_count: int
    win_rate: float
    final_equity: float


class BacktestResult(BaseModel):
    stats: BacktestStats
    equity_curve: list[dict[str, Any]]
    backend: str = "cpu"


class MatrixRequest(BaseModel):
    """场景矩阵:多品种 × 多周期 × 时段/事件过滤 × 参数网格。"""

    symbols: list[str]
    intervals: list[str]
    strategy: str = "double_ma"
    param_grid: dict[str, list[float]] = Field(default_factory=dict)
    start: str | None = None
    end: str | None = None
    capital: float = 1_000_000.0
    time_filters: list[TimeOfDayFilter] = Field(default_factory=lambda: [TimeOfDayFilter()])
    event_filters: list[EventFilter] = Field(default_factory=lambda: [EventFilter()])
    prefer_gpu: bool = True


class MatrixCell(BaseModel):
    symbol: str
    interval: str
    params: dict[str, float]
    time_filter: dict[str, int]
    event_filter: dict[str, Any]
    stats: BacktestStats


class MatrixResult(BaseModel):
    cells: list[MatrixCell]
    backend: str
    elapsed_ms: float
    combo_count: int
