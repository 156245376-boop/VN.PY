from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from test_local_backtest import config, dataset

from qf.backtest_parity import compare_runs
from qf.local_backtest import LocalBacktestEngine


def local_fixture():
    return LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=lambda: False
    )


def validation_fixture(**changes):
    local = local_fixture()
    payload = deepcopy(local.public())
    payload.update(
        run_id='20261020T120000-abcdef123456',
        engine_kind='tqsdk_validation',
    )
    payload.update(changes)
    return payload


def test_parity_compares_signals_fills_fees_and_terminal_equity():
    report = compare_runs(local_fixture(), validation_fixture())
    assert report.status == 'matched'
    assert report.signal_difference == 0
    assert report.fill_difference == 0
    assert report.fee_difference == '0'
    assert report.trade_count_difference == 0
    assert report.open_position_difference == 0
    assert report.equity_difference == '0'
    assert report.signal_fingerprint == report.signal_fingerprint
    assert report.fill_fingerprint == report.fill_fingerprint


def test_changed_fee_is_visible_as_a_fill_difference():
    validation = validation_fixture()
    validation['fills'] = deepcopy(validation['fills'])
    validation['fills'][0]['fee'] = '31'
    validation['fees'] = '63'
    report = compare_runs(local_fixture(), validation)
    assert report.status == 'differences'
    assert report.fill_difference == 1
    assert report.fee_difference == '1'
    assert report.first_divergence['kind'] == 'fill'
    assert report.first_divergence['index'] == 0


def test_equity_tolerance_is_explicit_and_bounded():
    validation = validation_fixture(final_equity='98816.01')
    report = compare_runs(
        local_fixture(), validation, equity_tolerance=Decimal('0.02')
    )
    assert report.status == 'matched'
    assert report.tolerance['equity'] == '0.02'


def test_unfinished_or_same_engine_runs_are_incomplete():
    unfinished = compare_runs(
        local_fixture(), validation_fixture(status='stopped')
    )
    assert unfinished.status == 'incomplete'
    same = compare_runs(local_fixture(), local_fixture())
    assert same.status == 'incomplete'
    assert same.reason == 'engine_identity_invalid'


def test_parity_can_accept_lightweight_evidence_objects():
    @dataclass
    class Evidence:
        run_id: str
        engine_kind: str
        status: str
        signals: list
        fills: list
        fees: Decimal
        closed_trade_count: int
        open_position: int
        final_equity: Decimal

    local = local_fixture()
    validation = Evidence(
        'validation-1',
        'tqsdk_validation',
        'backtest_finished',
        deepcopy(local.signals),
        deepcopy(local.fills),
        local.fees,
        local.closed_trade_count,
        local.open_position,
        local.final_equity,
    )
    assert compare_runs(local, validation).status == 'matched'
