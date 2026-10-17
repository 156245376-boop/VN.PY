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


def test_quote_units_follow_contract_type_and_unreturned_values_are_not_zero():
    market = importlib.import_module("qf.market")
    for exchange, product, expected in [
        ("SHFE", "rb", "元/吨"), ("SHFE", "au", "元/克"),
        ("SHFE", "ag", "元/千克"), ("INE", "sc", "元/桶"),
        ("INE", "ec", "点"), ("CFFEX", "IM", "点"),
        ("CFFEX", "T", "元/百元面值"), ("DCE", "jd", "元/500千克"),
        ("DCE", "fb", "元/立方米"), ("DCE", "bb", "元/张"),
        ("GFEX", "ps", "元/吨"), ("GFEX", "pt", "元/克"),
    ]:
        catalog = market.catalog_rows([{"instrument_id": f"KQ.m@{exchange}.{product}"}])[0]
        row = market.quote_row(catalog, {}, connected=True)
        assert row["price_unit"] == expected
        assert row["volume"] is None and row["open_interest"] is None
        assert row["data_note"]
    unknown = market.catalog_rows([{"instrument_id": "KQ.m@SHFE.zz"}])[0]
    assert market.quote_row(unknown, {}, connected=True)["price_unit"] == "单位待确认"
