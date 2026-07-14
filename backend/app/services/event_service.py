"""事件日历子系统。

三个来源:
1. manual  —— 用户可编辑的事件区间(如「美联储议息」「地缘冲突」)。
2. auto    —— 基于历史行情的自动异常波动检测(单日涨跌幅超过 N 倍标准差)。
3. seed    —— 预置的已知宏观事件种子。

回测通过 get_event_intervals / passes_time_filter 使用这些区间做过滤对比。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.core.db import get_connection, transaction
from app.models.schemas import Bar, EventFilter, EventItem, TimeOfDayFilter


def _ts(date_str: str, end_of_day: bool = False) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


# 预置宏观事件种子(可按需扩充)。日期为区间近似值,用户可在界面上编辑。
_SEED_EVENTS: list[dict[str, Any]] = [
    {"label": "俄乌冲突爆发", "category": "geopolitical", "start": "2022-02-24", "end": "2022-03-10"},
    {"label": "美联储激进加息启动", "category": "macro", "start": "2022-03-16", "end": "2022-03-17"},
    {"label": "硅谷银行倒闭", "category": "macro", "start": "2023-03-10", "end": "2023-03-13"},
    {"label": "中东局势升级", "category": "geopolitical", "start": "2023-10-07", "end": "2023-10-20"},
    {"label": "新冠疫情全球扩散", "category": "macro", "start": "2020-02-20", "end": "2020-03-23"},
]


def list_events(category: str | None = None) -> list[EventItem]:
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM events WHERE category = ? ORDER BY start_ts", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events ORDER BY start_ts").fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(r: Any) -> EventItem:
    return EventItem(
        id=r["id"],
        label=r["label"],
        category=r["category"],
        start_ts=r["start_ts"],
        end_ts=r["end_ts"],
        symbol=r["symbol"],
        source=r["source"],
        note=r["note"],
    )


def add_event(event: EventItem) -> EventItem:
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (label, category, start_ts, end_ts, symbol, source, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.label,
                event.category,
                event.start_ts,
                event.end_ts,
                event.symbol,
                event.source,
                event.note,
            ),
        )
        event.id = cur.lastrowid
    return event


def delete_event(event_id: int) -> bool:
    with transaction() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    return cur.rowcount > 0


def seed_events() -> int:
    """写入预置宏观事件种子(已存在同名同起始的则跳过)。返回新增条数。"""
    added = 0
    conn = get_connection()
    for ev in _SEED_EVENTS:
        start_ts = _ts(ev["start"])
        end_ts = _ts(ev["end"], end_of_day=True)
        exists = conn.execute(
            "SELECT 1 FROM events WHERE label = ? AND start_ts = ?",
            (ev["label"], start_ts),
        ).fetchone()
        if exists:
            continue
        add_event(
            EventItem(
                label=ev["label"],
                category=ev["category"],
                start_ts=start_ts,
                end_ts=end_ts,
                source="seed",
            )
        )
        added += 1
    return added


def detect_anomalies(symbol: str, bars: list[Bar], sigma: float = 3.0) -> list[EventItem]:
    """自动异常波动检测:按日聚合收益,标出偏离超过 sigma 倍标准差的日期。

    检测结果以 source='auto' 写入事件表(category='anomaly')。
    """
    if len(bars) < 5:
        return []
    daily: dict[int, float] = {}
    for b in bars:
        day = (b.ts // 86400) * 86400
        daily[day] = b.close
    days = sorted(daily.keys())
    closes = [daily[d] for d in days]
    returns: list[tuple[int, float]] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            returns.append((days[i], (closes[i] - prev) / prev))
    if len(returns) < 3:
        return []
    values = [r for _, r in returns]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = var ** 0.5
    if std == 0:
        return []
    detected: list[EventItem] = []
    for day, ret in returns:
        if abs(ret - mean) > sigma * std:
            ev = EventItem(
                label=f"{symbol} 异常波动 {ret*100:.1f}%",
                category="anomaly",
                start_ts=day,
                end_ts=day + 86399,
                symbol=symbol,
                source="auto",
                note=f"日收益 {ret*100:.2f}%,阈值 {sigma}σ",
            )
            detected.append(ev)
    conn = get_connection()
    for ev in detected:
        exists = conn.execute(
            "SELECT 1 FROM events WHERE symbol = ? AND start_ts = ? AND category = 'anomaly'",
            (symbol, ev.start_ts),
        ).fetchone()
        if not exists:
            add_event(ev)
    return detected


# ---- 供回测使用的过滤工具 ----

def get_event_intervals(event_filter: EventFilter) -> list[tuple[int, int]]:
    """按过滤配置返回需要匹配的事件区间列表。"""
    if event_filter.mode == "none" or not event_filter.categories:
        return []
    conn = get_connection()
    placeholders = ",".join("?" for _ in event_filter.categories)
    rows = conn.execute(
        f"SELECT start_ts, end_ts FROM events WHERE category IN ({placeholders})",
        event_filter.categories,
    ).fetchall()
    return [(r["start_ts"], r["end_ts"]) for r in rows]


def in_any_interval(ts: int, intervals: list[tuple[int, int]]) -> bool:
    for s, e in intervals:
        if s <= ts <= e:
            return True
    return False


_SECONDS_PER_DAY = 86400


def passes_time_filter(ts: int, tf: TimeOfDayFilter) -> bool:
    """时段过滤:排除每日开盘后 skip_open 分钟、收盘前 skip_close 分钟。

    简化模型:以自然日 UTC 秒的日内偏移做过滤。返回 True 表示该时间点保留。
    """
    if tf.skip_open_minutes == 0 and tf.skip_close_minutes == 0:
        return True
    sec_of_day = ts % _SECONDS_PER_DAY
    if sec_of_day < tf.skip_open_minutes * 60:
        return False
    if sec_of_day > _SECONDS_PER_DAY - tf.skip_close_minutes * 60:
        return False
    return True
