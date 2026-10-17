"""只汇总当前 SDK 订阅的历史质量；不代表内嵌图表独立请求的数据。"""

import pandas as pd

HISTORY_ISSUES = {"empty", "invalid_bar", "id_sequence", "time_order", "long_gap"}


def summarize_history(serial: pd.DataFrame, duration_seconds: int) -> dict:
    """区分合法前导占位与内部异常，不插值，也不推断缺失原因。"""
    result = {"valid_count": 0, "first": None, "last": None, "years": {}, "issues": []}
    columns = ["id", "datetime", "open", "high", "low", "close"]
    if serial.empty:
        result["issues"] = ["empty"]
        return result
    if not set(columns) <= set(serial.columns):
        result["issues"] = ["empty", "invalid_bar"]
        return result

    data = serial[columns].reset_index(drop=True).apply(pd.to_numeric, errors="coerce")
    finite = data.abs().lt(float("inf"))
    integer_id = finite["id"] & data["id"].mod(1).eq(0)
    prices = ["open", "high", "low", "close"]
    timestamps = pd.to_datetime(
        data["datetime"].where(finite["datetime"] & data["datetime"].gt(0)),
        unit="ns", utc=True, errors="coerce",
    ).dt.tz_convert("Asia/Shanghai")
    valid = (integer_id & data["id"].ge(0) & timestamps.notna()
             & finite[prices].all(axis=1))
    padding = (integer_id & data["id"].lt(0) & data["datetime"].eq(0)
               & data[prices].isna().all(axis=1))
    # SDK 数据不足 N 根时，只有开头的负 id、零时间和 NaN 价格属于正常占位。
    leading_padding = padding & padding.cummin()
    observed_ids = data.loc[~leading_padding, "id"]
    if not valid.any():
        result["issues"].append("empty")
    if (~(valid | leading_padding)).any():
        result["issues"].append("invalid_bar")
    if (not integer_id.loc[~leading_padding].all()
            or observed_ids.lt(0).any() or observed_ids.diff().dropna().ne(1).any()):
        result["issues"].append("id_sequence")
    observed_times = timestamps.loc[~leading_padding].dropna()
    intervals = observed_times.diff().dropna()
    if intervals.le(pd.Timedelta(0)).any():
        result["issues"].append("time_order")
    # 这里只标记日线中的可疑长间隔；分钟线正常的夜间、午间及休市不按周期报缺口。
    if duration_seconds == 86400 and intervals.gt(pd.Timedelta(days=31)).any():
        result["issues"].append("long_gap")

    valid_times = timestamps.loc[valid]
    if not valid_times.empty:
        result["valid_count"] = int(valid.sum())
        result["first"] = valid_times.min().strftime("%Y-%m-%d %H:%M:%S")
        result["last"] = valid_times.max().strftime("%Y-%m-%d %H:%M:%S")
        result["years"] = {str(year): int(count) for year, count in
                           valid_times.dt.year.value_counts().sort_index().items()}
    return result
