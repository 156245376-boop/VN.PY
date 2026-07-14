"""测试夹具:让每个测试用独立的临时 SQLite,避免污染真实数据库。"""
from __future__ import annotations

import importlib
import sqlite3

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """把数据库指向临时文件并重建结构。"""
    from app.core import config as config_mod
    from app.core import db as db_mod

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(config_mod.settings, "db_path", str(test_db))
    # 清掉线程本地连接,强制用新路径重连。
    if hasattr(db_mod._local, "conn"):
        try:
            db_mod._local.conn.close()
        except Exception:
            pass
        del db_mod._local.conn
    db_mod.init_db()
    yield db_mod
    if hasattr(db_mod._local, "conn"):
        try:
            db_mod._local.conn.close()
        except Exception:
            pass
        del db_mod._local.conn
