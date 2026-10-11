"""异常层级与 R32 五类故障处置方式的一一对应。

R32.2 要求「处置方式可由异常类型确定」。本文件断言该对应关系成立 —— 这是纯粹的
自有设计约定,预期值由实现方写定。

为什么值得测:这层对应关系一旦破损,表现不是报错,而是**捕获方按错误的策略处置**
—— 该停机的被重试,该回灌策略的被静默跳过。后者会亏钱。
"""

from __future__ import annotations

import pytest

from core import (
    CalendarMissing,
    CompliancePreflightFailed,
    ConfigInvalid,
    HaltRequired,
    InsufficientFunds,
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

pytestmark = pytest.mark.covers(
    "R32.1",
    "R32.2",
    "R32.3",
    "R32.4",
    "R32.5",
    "R32.7",
    "R32.8",
)

#: R32.3 —— 需立即停机并等待人工放行的四类故障。
HALT_CLASSES = [
    ReconcileMismatch,
    CompliancePreflightFailed,
    RiskCheckFailed,
    CalendarMissing,
]

#: R32.5 —— 需拒绝当前操作并通知策略的三类。
REJECT_CLASSES = [RiskVetoed, InsufficientFunds, PriceLimitBlocked]

ALL_CLASSES = [
    HaltRequired,
    StrategyFailure,
    Rejected,
    Retryable,
    Skipped,
    ConfigInvalid,
    SymbolAmbiguous,
    RetriesExhausted,
    *HALT_CLASSES,
    *REJECT_CLASSES,
]


@pytest.mark.parametrize("cls", ALL_CLASSES, ids=lambda c: c.__name__)
def test_all_errors_share_one_root(cls: type[Exception]) -> None:
    """单一根类使调用方能一次性区分「本系统的已分类故障」与「未预料的 bug」。"""
    assert issubclass(cls, QfError)


@pytest.mark.parametrize("cls", HALT_CLASSES, ids=lambda c: c.__name__)
def test_halt_classes_map_to_halt_state(cls: type[Exception]) -> None:
    """R32.3 的四类故障须均为 HaltRequired 子类,以便统一进入 Halt_State。"""
    assert issubclass(cls, HaltRequired)


@pytest.mark.parametrize("cls", REJECT_CLASSES, ids=lambda c: c.__name__)
def test_reject_classes_carry_reason(cls: type[Rejected]) -> None:
    """拒绝类必须携带原因文本 —— 该原因要回灌给策略(R17.13)。"""
    exc = cls("可用资金不足")
    assert isinstance(exc, Rejected)
    assert exc.reason == "可用资金不足"
    assert "可用资金不足" in str(exc)


def test_retries_exhausted_escalates_to_halt() -> None:
    """R32.8:有界重试的终点必须是停机,不能是静默放弃。

    这条对应 D4:写库持续失败时无上界重试会让内存缓冲无限增长 → OOM → 全部丢失。
    """
    assert issubclass(RetriesExhausted, HaltRequired)
    assert not issubclass(Retryable, HaltRequired), (
        "Retryable 本身不应是停机类 —— 否则第一次暂态失败就会停机"
    )


def test_disposition_classes_are_mutually_exclusive() -> None:
    """五类处置互不重叠 —— 否则「看类型即知处置方式」不成立。

    ConfigInvalid 与 SymbolAmbiguous 刻意不属于五类之一:前者发生在启动阶段
    (直接终止启动而非进入 Halt_State),后者是数据解析错误,由调用点按上下文决定
    是终止导入还是计数跳过。
    """
    groups = [HaltRequired, StrategyFailure, Rejected, Retryable, Skipped]
    for i, a in enumerate(groups):
        for b in groups[i + 1 :]:
            assert not issubclass(a, b) and not issubclass(b, a), (
                f"{a.__name__} 与 {b.__name__} 存在继承关系,处置方式将有歧义"
            )


def test_skipped_is_not_halt_or_reject() -> None:
    """单条记录级问题不得升级 —— 全市场录制下这类记录每天数千条(D1)。"""
    assert not issubclass(Skipped, HaltRequired)
    assert not issubclass(Skipped, Rejected)


def test_missing_session_spec_is_skipped_while_missing_calendar_halts() -> None:
    """R32.3/R32.7:缺一个品种的时段配置只跳过该品种;日期超出日历覆盖才停机。

    两者若归入同一类,要么一个未配置品种冻结全市场,要么日历缺口被静默跳过。
    """
    assert issubclass(SessionSpecMissing, Skipped)
    assert not issubclass(SessionSpecMissing, HaltRequired)
    assert issubclass(CalendarMissing, HaltRequired)
    assert not issubclass(CalendarMissing, Skipped)


def test_strategy_failure_does_not_halt_whole_system() -> None:
    """R11.15:停该实例,其他实例继续运行。"""
    assert not issubclass(StrategyFailure, HaltRequired)


def test_config_invalid_is_not_halt_state() -> None:
    """配置错误发生在启动阶段,应终止启动流程(R22.8),而非进入 Halt_State。"""
    assert not issubclass(ConfigInvalid, HaltRequired)
