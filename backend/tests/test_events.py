"""事件日历与过滤边界测试。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import Bar, EventFilter, EventItem, TimeOfDayFilter
from app.services import event_service


def _ts(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


def test_seed_and_list(db):
    added = event_service.seed_events()
    assert added > 0
    # 再次写入应幂等,不重复。
    again = event_service.seed_events()
    assert again == 0
    events = event_service.list_events()
    assert len(events) == added


def test_add_and_delete(db):
    ev = event_service.add_event(
        EventItem(label="测试事件", category="macro", start_ts=100, end_ts=200)
    )
    assert ev.id is not None
    assert event_service.delete_event(ev.id) is True
    assert event_service.delete_event(ev.id) is False


def test_event_interval_matching(db):
    event_service.add_event(
        EventItem(label="e", category="macro", start_ts=1000, end_ts=2000)
    )
    intervals = event_service.get_event_intervals(
        EventFilter(mode="exclude", categories=["macro"])
    )
    assert event_service.in_any_interval(1500, intervals) is True
    assert event_service.in_any_interval(999, intervals) is False
    # 区间端点包含
    assert event_service.in_any_interval(1000, intervals) is True
    assert event_service.in_any_interval(2000, intervals) is True


def test_time_filter_open_close():
    tf = TimeOfDayFilter(skip_open_minutes=15, skip_close_minutes=15)
    # 一天开始后 10 分钟 -> 被过滤
    assert event_service.passes_time_filter(_ts(2024, 1, 1, 0, 10), tf) is False
    # 开盘后 20 分钟 -> 保留
    assert event_service.passes_time_filter(_ts(2024, 1, 1, 0, 20), tf) is True
    # 临近收盘(23:55)-> 被过滤
    assert event_service.passes_time_filter(_ts(2024, 1, 1, 23, 55), tf) is False
    # 无过滤时全部保留
    assert event_service.passes_time_filter(_ts(2024, 1, 1, 0, 1), TimeOfDayFilter()) is True


def test_detect_anomalies(db):
    bars = []
    base = _ts(2024, 1, 1)
    price = 100.0
    for i in range(20):
        # 平稳,只有第 10 天暴涨。
        price = price * (1.0 + (0.5 if i == 10 else 0.001))
        bars.append(Bar(ts=base + i * 86400, open=price, high=price, low=price, close=price, volume=1))
    detected = event_service.detect_anomalies("rb0", bars, sigma=3.0)
    assert len(detected) >= 1
    assert any(e.category == "anomaly" for e in detected)
