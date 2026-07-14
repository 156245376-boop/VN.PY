"""数据服务测试:CSV 导入、入库查询、多周期重采样。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import Bar
from app.services import data_service


def _ts(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


def test_import_csv_basic(db):
    content = (
        "datetime,open,high,low,close,volume\n"
        "2024-01-01 09:00:00,100,105,99,102,10\n"
        "2024-01-01 09:01:00,102,106,101,104,12\n"
    ).encode("utf-8")
    r = data_service.import_csv("rb0", content)
    assert r["written"] == 2
    assert r["skipped"] == 0
    bars = data_service.get_bars("rb0", "1m")
    assert len(bars) == 2
    assert bars[0].close == 102


def test_import_csv_chinese_headers_and_dirty_rows(db):
    content = (
        "时间,开盘,最高,最低,收盘,成交量\n"
        "2024-01-01 09:00:00,100,105,99,102,10\n"
        ",bad,row,here,,\n"                       # 脏行:时间为空 + 非数字
        "2024-01-01 09:02:00,102,90,101,104,12\n"  # high<low 被跳过
        "2024-01-01 09:03:00,102,106,101,104,12\n"
    ).encode("utf-8")
    r = data_service.import_csv("rb0", content)
    assert r["written"] == 2
    assert r["skipped"] == 2


def test_import_csv_missing_column(db):
    content = b"datetime,open,high,low\n2024-01-01,1,2,0\n"
    try:
        data_service.import_csv("rb0", content)
        assert False, "应因缺列报错"
    except ValueError as e:
        assert "close" in str(e)


def test_import_csv_empty(db):
    try:
        data_service.import_csv("rb0", b"")
        assert False
    except ValueError:
        pass


def test_resample_5m():
    # 构造 10 根 1m,验证聚合到 5m 得到 2 根,OHLC 正确。
    bars = []
    base = _ts(2024, 1, 1, 0, 0)
    for i in range(10):
        price = 100 + i
        bars.append(Bar(ts=base + i * 60, open=price, high=price + 1, low=price - 1, close=price, volume=1))
    out = data_service.resample(bars, "5m")
    assert len(out) == 2
    # 第一根 5m:open 来自第一根,high 是桶内最高,close 来自第五根
    assert out[0].open == 100
    assert out[0].high == 105  # 104+1
    assert out[0].low == 99    # 100-1
    assert out[0].close == 104
    assert out[0].volume == 5


def test_resample_preserves_ohlc_invariants():
    bars = []
    base = _ts(2024, 1, 1)
    for i in range(60):
        p = 100 + (i % 7)
        bars.append(Bar(ts=base + i * 60, open=p, high=p + 2, low=p - 2, close=p, volume=1))
    for interval in ("5m", "15m", "30m", "1h"):
        out = data_service.resample(bars, interval)
        for b in out:
            assert b.high >= b.low
            assert b.high >= b.open and b.high >= b.close
            assert b.low <= b.open and b.low <= b.close
