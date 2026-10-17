import importlib
import json

import pandas as pd
import pytest


def bars(dates):
    stamps = [pd.Timestamp(value, tz="Asia/Shanghai").value for value in dates]
    return pd.DataFrame({"id": list(range(len(dates))), "datetime": stamps,
                         "open": [10.] * len(dates), "high": [12.] * len(dates),
                         "low": [9.] * len(dates), "close": [11.] * len(dates)})


def summarize(serial, duration=86400):
    return importlib.import_module("qf.history").summarize_history(serial, duration)


def test_history_counts_valid_rows_and_uses_beijing_dates():
    serial = bars(["2025-12-31", "2026-01-05", "2026-01-06"])
    serial["private-token"] = "private-value"
    assert summarize(serial) == {"valid_count": 3, "first": "2025-12-31 00:00:00",
                                 "last": "2026-01-06 00:00:00",
                                 "years": {"2025": 1, "2026": 2}, "issues": []}
    assert "private-" not in json.dumps(summarize(serial))


def test_legitimate_leading_placeholders_do_not_hide_short_history():
    serial = bars(["2026-10-15", "2026-10-16"])
    padding = pd.DataFrame({"id": [-2, -1], "datetime": [0, 0],
                            "open": [float("nan")] * 2, "high": [float("nan")] * 2,
                            "low": [float("nan")] * 2, "close": [float("nan")] * 2})
    result = summarize(pd.concat([padding, serial], ignore_index=True))
    assert result["valid_count"] == 2 and result["issues"] == []
    assert result["first"] == "2026-10-15 00:00:00"


@pytest.mark.parametrize("serial", [pd.DataFrame(), pd.DataFrame({
    "id": [-2, -1], "datetime": [0, 0], "open": [float("nan")] * 2,
    "high": [float("nan")] * 2, "low": [float("nan")] * 2, "close": [float("nan")] * 2})])
def test_initialized_empty_history_is_reported_without_inventing_a_range(serial):
    assert summarize(serial) == {"valid_count": 0, "first": None, "last": None,
                                 "years": {}, "issues": ["empty"]}


@pytest.mark.parametrize(("column", "value"), [
    ("datetime", 0), ("datetime", float("inf")), ("datetime", float("nan")),
    ("open", float("nan")), ("high", float("inf")),
    ("low", float("-inf")), ("close", float("nan")),
])
def test_invalid_internal_bar_is_detected_even_when_range_endpoints_are_present(column, value):
    serial = bars(["2026-01-05", "2026-01-06", "2026-01-07"]).astype(float)
    serial.loc[1, column] = value
    result = summarize(serial)
    assert result["valid_count"] == 2
    assert "invalid_bar" in result["issues"]
    assert result["first"] == "2026-01-05 00:00:00"
    assert result["last"] == "2026-01-07 00:00:00"


@pytest.mark.parametrize("ids", [[0, 2, 3], [0, 0, 1], [0, 0.5, 1], [0, -1, 1]])
def test_serial_id_gaps_duplicates_and_internal_padding_are_rejected(ids):
    serial = bars(["2026-01-05", "2026-01-06", "2026-01-07"])
    serial["id"] = ids
    assert "id_sequence" in summarize(serial)["issues"]


@pytest.mark.parametrize("dates", [
    ["2026-01-05", "2026-01-05", "2026-01-07"],
    ["2026-01-06", "2026-01-05", "2026-01-07"],
])
def test_duplicate_or_reversed_timestamps_are_rejected(dates):
    assert "time_order" in summarize(bars(dates))["issues"]


def test_years_between_valid_endpoints_are_not_assumed_present():
    result = summarize(bars(["2016-01-05", "2026-10-16"]))
    assert result["years"] == {"2016": 1, "2026": 1}
    assert result["issues"] == ["long_gap"]


@pytest.mark.parametrize("dates", [
    ["2026-01-09", "2026-01-12"],
    ["2026-02-13", "2026-02-24"],
    ["2022-01-01", "2022-01-26"],
    ["2026-01-01", "2026-02-01"],
])
def test_weekends_holidays_and_gaps_of_at_most_31_days_are_not_called_long_gaps(dates):
    assert summarize(bars(dates))["issues"] == []


def test_long_interval_rule_is_not_applied_to_intraday_trading_breaks():
    assert summarize(bars(["2025-12-01", "2026-01-05"]), 60)["issues"] == []
