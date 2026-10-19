from importlib import import_module


def test_calendar_handles_weekends_holidays_and_missing_middle_day():
    assess = import_module('qf.research_coverage').assess_coverage
    expected = ['2025-03-03', '2025-03-04', '2025-03-06']
    assert assess(expected_days=expected, observed_days=expected, issues=[])['status'] == 'verified'
    missing = assess(expected_days=expected, observed_days=['2025-03-03', '2025-03-06'],
                     issues=[])
    assert missing['status'] == 'incomplete' and missing['missing_days'] == ['2025-03-04']
    assert assess(expected_days=None, observed_days=expected, issues=[])['status'] == 'unknown'
    assert assess(expected_days=[], observed_days=[], issues=[])['status'] == 'incomplete'
