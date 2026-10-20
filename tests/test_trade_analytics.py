import csv
import io
from decimal import Decimal

import pytest

from qf.trade_analytics import (
    filter_trades,
    normalize_trade_filters,
    trade_ledger_csv,
    trade_statistics,
)


def ledger():
    return {"trades": [
        {"trade_id": "one", "status": "closed", "direction": 1,
         "first_symbol": "SHFE.rb2505", "last_symbol": "SHFE.rb2505",
         "entry_time_ns": "1735780439000000000", "entry_price": "3301",
         "exit_time_ns": "1735782539000000000", "exit_price": "3315",
         "quantity": 5, "initial_stop": "3284", "final_stop": "3302",
         "exit_reason": "ma_reverse", "gross_pnl": "700", "fee": "30",
         "net_pnl": "670", "fill_count": 2},
        {"trade_id": "two", "status": "closed", "direction": -1,
         "first_symbol": "DCE.m2509", "last_symbol": "DCE.m2509",
         "entry_time_ns": "1735784039000000000", "entry_price": "3000",
         "exit_time_ns": "1735784639000000000", "exit_price": "3010",
         "quantity": 2, "initial_stop": "3012", "final_stop": "3002",
         "exit_reason": "initial_stop", "gross_pnl": "-200", "fee": "20",
         "net_pnl": "-220", "fill_count": 2},
        {"trade_id": "open", "status": "open", "direction": 1,
         "first_symbol": "SHFE.rb2505", "last_symbol": "SHFE.rb2505",
         "entry_time_ns": "1735953239000000000", "entry_price": "3200",
         "exit_time_ns": None, "exit_price": None, "quantity": 1,
         "initial_stop": "3180", "final_stop": "3190",
         "exit_reason": None, "gross_pnl": "0", "fee": "6",
         "net_pnl": None, "fill_count": 1},
    ]}


def test_trade_filters_and_statistics_reconcile():
    filters = normalize_trade_filters({
        "direction": "1", "status": "closed", "symbol": "SHFE.rb2505"})
    trades = filter_trades(ledger(), filters)
    assert [trade["trade_id"] for trade in trades] == ["one"]
    assert trade_statistics(trades) == {
        "count": 1, "closed_count": 1, "open_count": 0,
        "wins": 1, "losses": 0, "flat": 0, "win_rate": "100",
        "gross_pnl": "700", "fee": "30", "net_pnl": "670",
        "average_win": "670", "average_loss": "0",
        "max_win": "670", "max_loss": "0",
    }


def test_filters_validate_dates_amounts_and_unknown_fields():
    assert normalize_trade_filters({"direction": "", "status": "all"}) == {
        "direction": None, "status": None, "symbol": None, "reason": None,
        "start": None, "end": None, "min_net": None, "max_net": None}
    filters = normalize_trade_filters({
        "start": "2025-01-02", "end": "2025-01-02",
        "min_net": "-1000", "max_net": "1000"})
    assert [trade["trade_id"] for trade in filter_trades(ledger(), filters)] == [
        "one", "two"]
    for bad in ({"direction": 2}, {"status": "lost"},
                {"start": "2025-02-30"}, {"min_net": "nan"},
                {"unexpected": "private"}):
        with pytest.raises(ValueError):
            normalize_trade_filters(bad)


def test_open_trade_fee_is_reported_but_not_counted_as_win_or_net():
    stats = trade_statistics(filter_trades(ledger(), normalize_trade_filters({})))
    assert stats["count"] == 3 and stats["closed_count"] == 2
    assert stats["open_count"] == 1
    assert stats["wins"] == 1 and stats["losses"] == 1
    assert stats["win_rate"] == "50"
    assert stats["fee"] == "56"
    assert stats["net_pnl"] == "450"
    assert stats["average_win"] == "670"
    assert stats["average_loss"] == "-220"
    assert stats["max_win"] == "670" and stats["max_loss"] == "-220"


def test_csv_uses_visible_columns_and_preserves_exact_totals():
    trades = filter_trades(ledger(), normalize_trade_filters({"status": "closed"}))
    text = trade_ledger_csv(trades)
    assert text.startswith("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    assert [row["交易编号"] for row in rows] == ["one", "two"]
    assert sum(Decimal(row["净盈亏（元）"]) for row in rows) == Decimal("450")
    assert rows[0]["初始止损"] == "3284"
