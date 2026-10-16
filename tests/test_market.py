import importlib
import math


def test_searches_chinese_code_and_exchange():
    market = importlib.import_module("qf.market")
    rows = market.catalog_rows([
        {"instrument_id": "KQ.m@SHFE.rb", "instrument_name": "螺纹钢主连"},
        {"instrument_id": "KQ.m@DCE.m", "instrument_name": "豆粕主连"},
        {"instrument_id": "SSE.600000", "instrument_name": "股票"},
    ])
    assert len(rows) == 2
    for text in ("螺纹钢", "RB", "SHFE"):
        assert market.filter_catalog(rows, text, None)[0]["continuous"] == "KQ.m@SHFE.rb"
    assert market.filter_catalog(rows, "螺纹钢", "DCE") == []


def test_missing_name_and_nonfinite_prices_are_explicit():
    market = importlib.import_module("qf.market")
    item = market.catalog_rows([{"instrument_id": "KQ.m@SHFE.rb"}])[0]
    assert item["name"] == "rb"
    row = market.quote_row(item, {"last_price": math.nan, "pre_settlement": 0}, connected=True)
    assert row["last_price"] is None and row["change_percent"] is None
    assert row["data_state"] == "waiting"
    row = market.quote_row(item, {"last_price": 3300, "pre_settlement": 3000,
                                  "datetime": "2026-10-16 14:59:59.000000"}, connected=True)
    assert row["change_percent"] == 10
    assert row["data_state"] == "ready"
    offline = market.quote_row(item, row, connected=False)
    assert offline["data_state"] == "disconnected"
