from datetime import date

import pytest

from qf.data_catalog import CoverageReport, DataCapability, DataRequest


def request(**changes):
    values = dict(
        continuous='KQ.m@SHFE.rb',
        symbol='SHFE.rb2505',
        bar_seconds=60,
        start=date(2025, 1, 2),
        end=date(2025, 1, 10),
        precision='minute',
    )
    values.update(changes)
    return DataRequest(**values)


def test_data_request_key_is_stable_and_round_trips():
    value = request()
    assert value.key() == value.key()
    assert value.public() == {
        'continuous': 'KQ.m@SHFE.rb',
        'symbol': 'SHFE.rb2505',
        'bar_seconds': 60,
        'start': '2025-01-02',
        'end': '2025-01-10',
        'precision': 'minute',
    }
    assert DataRequest.from_public(value.public()) == value


def test_data_request_rejects_invalid_identity_and_range():
    for bad in (
        request(continuous='rb'),
        request(symbol='private'),
        request(bar_seconds=0),
        request(start=date(2025, 1, 11)),
        request(precision='daily'),
        request(start='2025-01-02'),
    ):
        with pytest.raises(ValueError):
            bad.validate()


def test_coverage_requires_every_expected_trading_day():
    report = CoverageReport(
        expected_days=[date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)],
        observed_days=[date(2025, 1, 2), date(2025, 1, 6)],
        issues=[],
    )
    assert not report.complete()
    assert report.missing_days() == [date(2025, 1, 3)]
    full = CoverageReport(
        expected_days=report.expected_days,
        observed_days=report.expected_days,
        issues=[],
    )
    assert full.complete() and full.missing_days() == []


def test_coverage_rejects_duplicate_extra_days_and_unknown_issues():
    for values in (
        dict(expected_days=[date(2025, 1, 2), date(2025, 1, 2)],
             observed_days=[date(2025, 1, 2)], issues=[]),
        dict(expected_days=[date(2025, 1, 2)],
             observed_days=[date(2025, 1, 3)], issues=[]),
        dict(expected_days=[date(2025, 1, 2)],
             observed_days=[date(2025, 1, 2)], issues=['private']),
    ):
        with pytest.raises(ValueError):
            CoverageReport(**values).validate()


def test_capability_is_explicit_and_public_safe():
    available = DataCapability(
        status='available', reason='ok', minute_available=True,
        tick_available=False, source='DataDownloader')
    assert available.public() == {
        'status': 'available', 'reason': 'ok', 'minute_available': True,
        'tick_available': False, 'source': 'DataDownloader'}
    with pytest.raises(ValueError):
        DataCapability(status='unknown', reason='x', minute_available=False,
                       tick_available=False, source='x').validate()
