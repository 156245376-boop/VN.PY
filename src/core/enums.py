"""共享枚举 —— 全系统对同一概念的唯一说法。

core 不得依赖任何交易框架(见 ADR-0004)。这些取值到 vnpy 词汇的转换只发生在
engines/vnpy_bridge.py 与 gateway/ 两处,使领域层可被自研引擎复用。
"""

from enum import StrEnum

__all__ = [
    "AdjustmentMethod",
    "Direction",
    "Disposition",
    "Exchange",
    "Interval",
    "Offset",
    "Severity",
]


class Direction(StrEnum):
    """买卖方向。"""

    LONG = "long"
    SHORT = "short"


class Offset(StrEnum):
    """开平标志。

    CLOSE 为未解析状态;上期所与能源中心必须显式拆为 CLOSE_TODAY/CLOSE_YESTERDAY
    后才可报单(R17.7),该解析由 execution/offsets.py 负责,不由策略决定。
    """

    OPEN = "open"
    CLOSE = "close"
    CLOSE_TODAY = "close_today"
    CLOSE_YESTERDAY = "close_yesterday"


class Exchange(StrEnum):
    """国内期货交易所。取值同时用作 Canonical_Symbol 的后缀(R27.1)。"""

    SHFE = "SHFE"
    INE = "INE"
    DCE = "DCE"
    CZCE = "CZCE"
    CFFEX = "CFFEX"
    GFEX = "GFEX"


class Interval(StrEnum):
    """K 线周期。"""

    MINUTE = "1m"
    DAILY = "1d"


class Severity(StrEnum):
    """数据质量异常的严重级别(R8.8)。

    ERROR 会触发 Curated_Layer 的发布闸门(R8.11)。
    """

    ERROR = "ERROR"
    WARNING = "WARNING"


class Disposition(StrEnum):
    """告警的处置类别(R21.3)。"""

    MANUAL_RELEASE = "manual_release"
    ATTENTION = "attention"
    RECORD_ONLY = "record_only"


class AdjustmentMethod(StrEnum):
    """换月复权方式(R28.6)。

    四种方式各有偏差且必须显式选择:无复权有假跳空;后复权远端价格可能变负;
    前复权每次新换月会重写整条历史,故不版本化冻结时不可复现(B5);比例复权
    扭曲绝对价位使以 tick 计的止损失去意义。取值编入存储路径(R28.7)。
    """

    NONE = "none"
    FORWARD = "forward"
    BACKWARD = "backward"
    RATIO = "ratio"
