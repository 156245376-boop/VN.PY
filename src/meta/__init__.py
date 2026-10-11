"""meta (L2) —— 某日期下的市场参考事实。

合约表、交易日历与时段、费率保证金 SCD-2、合约代码规范化(R3/R27/R30)。

**本模块拥有参考事实及其读取端口**:`ReferenceDataStore` 与值模型住在这里,
而不是 L3 的 `data`。理由是交易日历、时段、费率属"某日期下的市场事实",
与行情存储是两回事;若经 `data` 读取,就是 L2 反向依赖 L3,分层契约当场破裂,
且回测路径会被迫拖进行情存储。

公开接口、不变式与禁止 import 见同目录 README.md。
Phase 1 已落地 calendar / symbols / store;合约表与费率保证金(Phase 4)仍为存根。
"""

from meta.calendar import TradingCalendar
from meta.models import (
    SessionKind,
    SessionWindow,
    TradingDayRecord,
    TradingSessionSpec,
)
from meta.store import ReferenceDataStore
from meta.symbols import (
    is_combination,
    is_continuous,
    split_canonical,
    to_canonical,
    to_wire,
)

__all__ = [
    "ReferenceDataStore",
    "SessionKind",
    "SessionWindow",
    "TradingCalendar",
    "TradingDayRecord",
    "TradingSessionSpec",
    "is_combination",
    "is_continuous",
    "split_canonical",
    "to_canonical",
    "to_wire",
]
