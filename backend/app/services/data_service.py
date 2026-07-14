"""历史数据服务:K 线读写、akshare 在线下载、CSV 导入、多周期重采样。

akshare 为可选依赖:未安装时下载功能不可用,但 CSV 导入与已入库数据的查询/
重采样照常工作(优雅降级)。
"""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Any

from app.core.db import get_connection, transaction
from app.models.schemas import INTERVAL_SECONDS, Bar, SymbolInfo


def _now_ts() -> int:
    return int(time.time())


def _date_to_ts(date_str: str, end_of_day: bool = False) -> int:
    """把 YYYY-MM-DD 转成 Unix 秒(按本地自然日,UTC 存储)。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


# ---- 读取与概览 ----

def list_symbols() -> list[SymbolInfo]:
    """列出已入库的合约及其数据概览。"""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT b.symbol AS symbol,
               s.name AS name,
               s.exchange AS exchange,
               COUNT(*) AS bar_count,
               MIN(b.ts) AS first_ts,
               MAX(b.ts) AS last_ts
        FROM bars b
        LEFT JOIN symbols s ON s.symbol = b.symbol
        WHERE b.interval = '1m'
        GROUP BY b.symbol
        ORDER BY b.symbol
        """
    ).fetchall()
    return [
        SymbolInfo(
            symbol=r["symbol"],
            name=r["name"],
            exchange=r["exchange"],
            bar_count=r["bar_count"],
            first_ts=r["first_ts"],
            last_ts=r["last_ts"],
        )
        for r in rows
    ]


def get_bars(
    symbol: str,
    interval: str = "1m",
    start: str | None = None,
    end: str | None = None,
    limit: int = 5000,
) -> list[Bar]:
    """读取 K 线。非 1m 周期由 1m 基础数据实时重采样得到。"""
    base = _read_base_bars(symbol, start, end)
    if interval != "1m":
        base = resample(base, interval)
    if limit and len(base) > limit:
        base = base[-limit:]
    return base


def _read_base_bars(symbol: str, start: str | None, end: str | None) -> list[Bar]:
    conn = get_connection()
    query = "SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ? AND interval = '1m'"
    params: list[Any] = [symbol]
    if start:
        query += " AND ts >= ?"
        params.append(_date_to_ts(start))
    if end:
        query += " AND ts <= ?"
        params.append(_date_to_ts(end, end_of_day=True))
    query += " ORDER BY ts ASC"
    rows = conn.execute(query, params).fetchall()
    return [
        Bar(
            ts=r["ts"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
        )
        for r in rows
    ]


# ---- 多周期重采样 ----

def resample(bars: list[Bar], interval: str) -> list[Bar]:
    """把 1m 基础 K 线聚合为更大周期。

    以每根 K 线时间戳所属的周期桶归组:桶内首开、最高、最低、末收、量求和。
    """
    if interval not in INTERVAL_SECONDS:
        raise ValueError(f"不支持的周期: {interval}")
    if interval == "1m" or not bars:
        return bars
    bucket_size = INTERVAL_SECONDS[interval]
    out: list[Bar] = []
    cur_bucket: int | None = None
    o = h = l = c = 0.0
    vol = 0.0
    for bar in bars:
        bucket = (bar.ts // bucket_size) * bucket_size
        if cur_bucket is None:
            cur_bucket = bucket
            o, h, l, c, vol = bar.open, bar.high, bar.low, bar.close, bar.volume
        elif bucket == cur_bucket:
            h = max(h, bar.high)
            l = min(l, bar.low)
            c = bar.close
            vol += bar.volume
        else:
            out.append(Bar(ts=cur_bucket, open=o, high=h, low=l, close=c, volume=vol))
            cur_bucket = bucket
            o, h, l, c, vol = bar.open, bar.high, bar.low, bar.close, bar.volume
    if cur_bucket is not None:
        out.append(Bar(ts=cur_bucket, open=o, high=h, low=l, close=c, volume=vol))
    return out


# ---- 写入 ----

def _upsert_bars(symbol: str, bars: list[Bar]) -> int:
    """写入 1m K 线(去重覆盖)。返回写入条数。"""
    if not bars:
        return 0
    with transaction() as conn:
        conn.executemany(
            """
            INSERT INTO bars (symbol, interval, ts, open, high, low, close, volume)
            VALUES (?, '1m', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval, ts) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
            """,
            [
                (symbol, b.ts, b.open, b.high, b.low, b.close, b.volume)
                for b in bars
            ],
        )
        conn.execute(
            """
            INSERT INTO symbols (symbol, name, exchange, updated_at)
            VALUES (?, NULL, NULL, ?)
            ON CONFLICT(symbol) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (symbol, _now_ts()),
        )
    return len(bars)


# ---- CSV 导入 ----

_COLUMN_ALIASES = {
    "ts": {"ts", "time", "datetime", "date", "时间", "日期"},
    "open": {"open", "o", "开", "开盘", "开盘价"},
    "high": {"high", "h", "高", "最高", "最高价"},
    "low": {"low", "l", "低", "最低", "最低价"},
    "close": {"close", "c", "收", "收盘", "收盘价"},
    "volume": {"volume", "vol", "v", "量", "成交量"},
}


def _match_column(header: list[str]) -> dict[str, int]:
    """把 CSV 表头映射到标准字段索引。"""
    mapping: dict[str, int] = {}
    lowered = [h.strip().lower() for h in header]
    for field, aliases in _COLUMN_ALIASES.items():
        for idx, col in enumerate(lowered):
            if col in aliases:
                mapping[field] = idx
                break
    return mapping


def _parse_ts(value: str) -> int:
    """解析多种时间格式为 Unix 秒。"""
    value = value.strip()
    if value.isdigit():
        num = int(value)
        # 毫秒时间戳
        return num // 1000 if num > 10_000_000_000 else num
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {value}")


def import_csv(symbol: str, content: bytes) -> dict[str, Any]:
    """导入 CSV 文本为 1m K 线。返回导入统计与跳过的脏行数。"""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("空文件")
    header = rows[0]
    mapping = _match_column(header)
    required = {"ts", "open", "high", "low", "close"}
    missing = required - mapping.keys()
    if missing:
        raise ValueError(f"缺少必要列: {', '.join(sorted(missing))}")
    bars: list[Bar] = []
    skipped = 0
    for raw in rows[1:]:
        if not raw or len(raw) < len(header):
            skipped += 1
            continue
        try:
            ts = _parse_ts(raw[mapping["ts"]])
            o = float(raw[mapping["open"]])
            h = float(raw[mapping["high"]])
            l = float(raw[mapping["low"]])
            c = float(raw[mapping["close"]])
            v = float(raw[mapping["volume"]]) if "volume" in mapping else 0.0
            if h < l:
                skipped += 1
                continue
            bars.append(Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v))
        except (ValueError, IndexError):
            skipped += 1
            continue
    written = _upsert_bars(symbol, bars)
    return {"symbol": symbol, "written": written, "skipped": skipped, "total_rows": len(rows) - 1}


# ---- akshare 在线下载(可选依赖) ----

def akshare_available() -> bool:
    try:
        import akshare  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def download(symbol: str, start: str, end: str, interval: str = "1m") -> dict[str, Any]:
    """用 akshare 下载国内期货历史 K 线并入库。

    akshare 未安装时抛出清晰错误,由上层转成对用户友好的提示。
    """
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # 优雅降级:提示改用 CSV 导入
        raise RuntimeError(
            "akshare 未安装,无法在线下载。请先 pip install akshare,或改用 CSV 导入。"
        ) from exc

    # akshare 期货分钟线接口:futures_zh_minute_sina(symbol, period)
    period_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60"}
    try:
        if interval == "1d":
            df = ak.futures_zh_daily_sina(symbol=symbol)
        else:
            period = period_map.get(interval, "1")
            df = ak.futures_zh_minute_sina(symbol=symbol, period=period)
    except Exception as exc:
        raise RuntimeError(f"akshare 下载失败: {exc}") from exc

    bars = _dataframe_to_bars(df)
    start_ts = _date_to_ts(start)
    end_ts = _date_to_ts(end, end_of_day=True)
    bars = [b for b in bars if start_ts <= b.ts <= end_ts]
    written = _upsert_bars(symbol, bars)
    return {"symbol": symbol, "written": written, "requested": [start, end], "interval": interval}


def _dataframe_to_bars(df: Any) -> list[Bar]:
    """把 akshare 返回的 DataFrame 规整为 1m Bar 列表。"""
    cols = {c.lower(): c for c in df.columns}
    def col(*names: str) -> str | None:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    ts_col = col("datetime", "date", "time")
    o_col = col("open")
    h_col = col("high")
    l_col = col("low")
    c_col = col("close")
    v_col = col("volume", "hold")
    bars: list[Bar] = []
    for _, row in df.iterrows():
        try:
            raw_ts = row[ts_col]
            if hasattr(raw_ts, "timestamp"):
                ts = int(raw_ts.replace(tzinfo=timezone.utc).timestamp()) if raw_ts.tzinfo is None else int(raw_ts.timestamp())
            else:
                ts = _parse_ts(str(raw_ts))
            bars.append(
                Bar(
                    ts=ts,
                    open=float(row[o_col]),
                    high=float(row[h_col]),
                    low=float(row[l_col]),
                    close=float(row[c_col]),
                    volume=float(row[v_col]) if v_col else 0.0,
                )
            )
        except (ValueError, TypeError, KeyError):
            continue
    return bars
