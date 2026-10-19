import copy
import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from pivot_sdk import PivotApi, sdk_for_pivot
from research_helpers import pivot_config_data

from qf.research_config import validate_research_config
from qf.research_journal import ResearchJournal
from qf.research_runtime import execute_research


def config():
    raw = pivot_config_data()
    raw['end'] = raw['start']
    return validate_research_config(raw)


def test_live_snapshot_is_committed_and_has_no_future_or_credentials(tmp_path):
    frames, stages = [], []
    result = execute_research('backtest', config(), tmp_path, ('u', 'private-password'),
        sdk=sdk_for_pivot(), view_progress=lambda value: frames.append(copy.deepcopy(value)),
        progress=lambda stage, **fields: stages.append((stage, fields)))
    assert result['status'] == 'backtest_finished'
    assert PivotApi.instances[-1].targets == [16, 0]
    assert frames and frames[-1]['terminal'] and frames[-1]['progress']['percent'] == 100
    assert len({f['revision'] for f in frames}) == len(frames)
    assert 'private-password' not in json.dumps(frames)
    for frame in frames:
        as_of = int(frame['as_of_ns'])
        assert all(int(b['time_ns']) <= as_of for b in frame['bars'])
        assert all(int(f['time_ns']) <= as_of for f in frame['fills'])
        assert len(frame['bars']) <= 500 and len(frame['risk_events']) <= 5000
    assert frames[-1]['entry_plan']['stop_price'] == '995.0'
    assert result['summary']['closed_trade_count'] == 1
    assert any(s == 'research_progress' and f['details']['stage'] == 'saving' for s, f in stages)


def test_entry_cancel_late_fill_and_price_beyond_stop(tmp_path):
    cfg = replace(config(), risk=replace(config().risk, risk_budget=Decimal(180)))
    result = execute_research('backtest', cfg, tmp_path, ('u', 'p'), sdk=sdk_for_pivot('partial'))
    assert result['status'] == 'backtest_finished'
    api = PivotApi.instances[-1]
    assert api.targets == [3, 0]
    assert sum(t.volume for t in api.trades.values() if t.offset == 'CLOSE') == 3
    assert result['summary']['open_position'] == 0
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
                              sdk=sdk_for_pivot('beyond_stop'))
    assert result['status'] == 'backtest_finished'
    assert PivotApi.instances[-1].targets == [16, 0]


@pytest.mark.parametrize('scenario', ['calendar_missing', 'reject', 'disconnect'])
def test_failure_never_publishes_successful_100(tmp_path, scenario):
    frames = []
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
                              sdk=sdk_for_pivot(scenario), view_progress=frames.append)
    assert result['status'] != 'backtest_finished'
    assert all(f['progress']['percent'] != 100 for f in frames)
    assert 'private-service-response' not in str(result)


def test_missing_middle_days_are_not_reported_as_whole_interval(tmp_path):
    cfg = replace(config(), end=config().end.replace(day=7))
    result = execute_research('backtest', cfg, tmp_path, ('u', 'p'), sdk=sdk_for_pivot())
    assert result['status'] != 'backtest_finished'
    assert result['reason'] == 'historical_coverage_incomplete'


def test_entry_plan_and_target_commit_atomically(tmp_path):
    j = ResearchJournal.create(tmp_path, 'backtest', config().public())
    j.db.execute("CREATE TRIGGER block_plan BEFORE INSERT ON risk_events "
                 "BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            j.commit_update('intent', time_ns=10, kind='intent', payload={
                'entry_plan': {'side': 1, 'lots': 16, 'stop_price': '995'}},
                risk_state=j.load_risk(), fills=[], target=16)
        assert j.get('entry_plan') is None and j.get('last_target') is None
    finally:
        j.close()


def test_chart_callback_failure_cannot_change_execution(tmp_path):
    def unavailable(_):
        raise RuntimeError('fixture closed chart')
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
                              sdk=sdk_for_pivot(), view_progress=unavailable)
    assert result['status'] == 'backtest_finished'
    assert PivotApi.instances[-1].targets == [16, 0]


def test_save_failure_never_reports_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(ResearchJournal, 'export', lambda self: (_ for _ in ()).throw(OSError()))
    frames = []
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
                              sdk=sdk_for_pivot(), view_progress=frames.append)
    assert result['reason'] == 'result_save_failed'
    assert all(frame['progress']['percent'] != 100 for frame in frames)


def test_confirmed_pivot_entry_is_same_for_backtest_and_paper(tmp_path):
    from qf.research_runtime import ResearchLoop, contract_spec
    plans = []
    for paper in (False, True):
        sdk = sdk_for_pivot()
        api, account = sdk.TqApi(), sdk.TqSim()
        cfg = config()
        serial = api.get_kline_serial(cfg.symbol, cfg.bar_seconds)
        journal = ResearchJournal.create(tmp_path, 'paper' if paper else 'backtest', cfg.public())
        spec = contract_spec(api, account, cfg.symbol, api.quote, paper=paper, multiplier=1)
        loop = ResearchLoop(sdk, api, account, journal, cfg, spec, paper=paper,
                            active=True, progress=None)
        loop.guard.start({}, {}, activate=True)
        api.execution_guard = loop.guard
        loop.step(api.quote, serial, minimum_bar=0, start_ns=0, end_ns=2**63-1, flatten=False)
        plans.append(loop.entry_plan)
        journal.close()
    assert plans[0] == plans[1] and plans[0].lots == 16


def test_same_time_pivot_confirmation_and_stale_quote(tmp_path):
    from qf.research_runtime import ResearchLoop, contract_spec
    sdk = sdk_for_pivot()
    api, account, cfg = sdk.TqApi(), sdk.TqSim(), config()
    serial = api.get_kline_serial(cfg.symbol, cfg.bar_seconds)
    j = ResearchJournal.create(tmp_path, 'backtest', cfg.public())
    loop = ResearchLoop(sdk, api, account, j, cfg,
        contract_spec(api, account, cfg.symbol, api.quote, paper=False, multiplier=1),
        paper=False, active=True, progress=None)
    loop.guard.start({}, {}, activate=True)
    api.execution_guard = loop.guard
    api.quote.datetime = '2025-03-03 09:04:59.000000'
    loop.step(api.quote, serial, minimum_bar=0, start_ns=0, end_ns=2**63-1, flatten=False)
    assert not api.targets
    api.quote.datetime = '2025-03-03 09:05:00.000000'
    loop.step(api.quote, serial, minimum_bar=0, start_ns=0, end_ns=2**63-1, flatten=False)
    assert api.targets == [16]
    assert loop.entry_plan.pivot.confirmed_ns <= loop.last_equity_ns
    j.close()


def test_frozen_initial_stop_survives_restart_check(tmp_path):
    sdk = sdk_for_pivot()
    first = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk)
    j = ResearchJournal(tmp_path/first['run_id'])
    plan = j.get('entry_plan')
    j.set('mode', 'paper')
    j.set('pending_intent', True)
    j.close()
    sdk = sdk_for_pivot()
    resumed = execute_research('paper', config(), tmp_path, ('u', 'p'),
                               sdk=sdk, resume=first['run_id'])
    assert resumed['reason'] == 'resume_incomplete'
    assert not PivotApi.instances
    j = ResearchJournal(tmp_path/first['run_id'])
    assert j.get('entry_plan') == plan
    j.close()
