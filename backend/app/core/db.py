"""SQLite 数据层:行情 K 线、合约、事件日历的建表与连接管理。

使用标准库 sqlite3,避免额外依赖。所有写入使用参数化查询,防止注入。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from app.core.config import settings

# WAL 模式下允许多读单写;每个线程使用独立连接。
_local = threading.local()


SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol     TEXT    NOT NULL,
    interval   TEXT    NOT NULL,
    ts         INTEGER NOT NULL,
    open       REAL    NOT NULL,
    high       REAL    NOT NULL,
    low        REAL    NOT NULL,
    close      REAL    NOT NULL,
    volume     REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, ts)
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_interval_ts
    ON bars (symbol, interval, ts);

CREATE TABLE IF NOT EXISTS symbols (
    symbol     TEXT PRIMARY KEY,
    name       TEXT,
    exchange   TEXT,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER NOT NULL,
    symbol     TEXT,
    source     TEXT    NOT NULL DEFAULT 'manual',
    note       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_range ON events (start_ts, end_ts);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_connection() -> sqlite3.Connection:
    """返回当前线程的连接(惰性创建)。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """事务上下文:成功提交,异常回滚。"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """初始化数据库结构(幂等)。"""
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
