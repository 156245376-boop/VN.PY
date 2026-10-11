"""全局测试夹具与 R34.7 的强制实现。

R34.7 要求:领域逻辑测试的预期值处于待填状态时,该测试的执行结果**必须为失败
而非通过**。

为什么需要机械强制:若预期值由生成实现的同一模型产出,测试退化为「模型的理解
== 模型的实现」的同义反复,证明力为零(ADR-0001)。约定是模型只写测试输入与
结构、预期值标记待填,由开发者查阅交易所公告、交易日历等外部权威资料后填入。

「完全跳过」这一种失效由本文件转为可观测。**「敷衍填入」——照抄实现当前的输出、
或向模型索取取值——仍然不可观测,且测试会全部通过。** 这是 ADR-0001 记录的主要
执行风险,无技术手段可缓解。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core import CHINA_TZ, ManualClock

PENDING_MARKER = "pending_expected"


def pytest_runtest_setup(item: pytest.Item) -> None:
    """使标记为 pending_expected 的用例必然失败(R34.7)。

    在 setup 阶段失败而非跳过 —— 跳过会在汇总里显示为绿色,等于把「预期值还没
    人工核对」这件事藏起来,而这恰好是本机制唯一无法自动化的环节。
    """
    marker = item.get_closest_marker(PENDING_MARKER)
    if marker is None:
        return
    note = marker.args[0] if marker.args else "未说明所需资料"
    pytest.fail(
        f"预期值待人工核对填入(R34.7):{note}\n"
        f"填入依据须为系统外部权威资料 —— 交易所公告、交易日历、券商确认的费率表。"
        f"不得照抄实现的当前输出,也不得向模型索取(ADR-0001)。",
        pytrace=False,
    )


@pytest.fixture
def clock() -> ManualClock:
    """固定在一个夜盘时刻的可推进时钟。

    取 2024-01-05(周五)21:30 —— 这是周五夜盘归属下周一这条规则的边界样本,
    使默认夹具本身就落在最容易出错的时段而非平淡的日盘中段。
    """
    return ManualClock(datetime(2024, 1, 5, 21, 30, tzinfo=CHINA_TZ))
