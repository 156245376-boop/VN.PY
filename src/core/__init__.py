"""core (L0) —— 全系统共享词汇。

本层不知道 vnpy、pandas、磁盘、网络、交易所规则与券商。它只定义"大家对同一个
东西的说法",使上层可以各自实现而不必互相阅读实现代码。
"""

from core.enums import (
    AdjustmentMethod,
    Direction,
    Disposition,
    Exchange,
    Interval,
    Offset,
    Severity,
)
from core.errors import (
    CalendarMissing,
    CompliancePreflightFailed,
    ConfigInvalid,
    HaltRequired,
    InsufficientFunds,
    NotInTradingSession,
    PriceLimitBlocked,
    QfError,
    ReconcileMismatch,
    Rejected,
    RetriesExhausted,
    Retryable,
    RiskCheckFailed,
    RiskVetoed,
    SessionSpecMissing,
    Skipped,
    StrategyFailure,
    SymbolAmbiguous,
)
from core.timeutil import CHINA_TZ, Clock, ManualClock, SystemClock, ensure_aware
from core.types import Bar, Fill, OrderIntent, Tick

__all__ = [
    "CHINA_TZ",
    "AdjustmentMethod",
    "Bar",
    "CalendarMissing",
    "Clock",
    "CompliancePreflightFailed",
    "ConfigInvalid",
    "Direction",
    "Disposition",
    "Exchange",
    "Fill",
    "HaltRequired",
    "InsufficientFunds",
    "Interval",
    "ManualClock",
    "NotInTradingSession",
    "Offset",
    "OrderIntent",
    "PriceLimitBlocked",
    "QfError",
    "ReconcileMismatch",
    "Rejected",
    "RetriesExhausted",
    "Retryable",
    "RiskCheckFailed",
    "RiskVetoed",
    "SessionSpecMissing",
    "Severity",
    "Skipped",
    "StrategyFailure",
    "SymbolAmbiguous",
    "SystemClock",
    "Tick",
    "ensure_aware",
]
