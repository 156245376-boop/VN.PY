"""交易日覆盖核对，不以猜测的工作日替代服务端日历。"""


def assess_coverage(*, expected_days, observed_days, issues):
    missing = sorted(set(expected_days or []) - set(observed_days))
    reasons = list(issues)
    if expected_days is None:
        reasons.append('trading_calendar_unavailable')
        status = 'unknown'
    elif not expected_days:
        reasons.append('no_trading_days')
        status = 'incomplete'
    else:
        if missing:
            reasons.append('missing_trading_days')
        status = 'incomplete' if reasons else 'verified'
    return dict(status=status, missing_days=missing, reasons=reasons)
