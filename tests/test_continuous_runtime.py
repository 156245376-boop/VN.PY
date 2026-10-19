import json
import sqlite3
from dataclasses import replace

import pytest
from continuous_sdk import SYMBOLS, ContinuousSdkFixture
from test_continuous_config import continuous_data

from qf.research_config import validate_research_config
from qf.research_runtime import execute_research


def config(**extra):
    raw = continuous_data() | dict(start='2025-01-03', end='2026-01-06',
        bar_seconds=60, fast_period=2, slow_period=4)
    raw['risk'].update(sizing='fixed', fixed_lots=1, pivot_left=1, pivot_right=1,
                       stairs_enabled=False, take_profit_value='100')
    return validate_research_config(raw | extra)


def run(root, fixture, **kw):
    return execute_research('backtest', config(), root, ('test-user', 'private-password'),
                             sdk=fixture.sdk, **kw)


def test_single_account_over_two_years_and_three_rolls(tmp_path):
    fixture = ContinuousSdkFixture()
    frames = []
    result = run(tmp_path, fixture, view_progress=frames.append)
    assert result['status'] == 'backtest_finished', result
    assert fixture.calls == {'TqApi': 1, 'TqSim': 1, 'TqBacktest': 1}
    assert result['summary']['roll_count'] == 3
    api = fixture.apis[0]
    assert api.closed
    assert {s for _, s, _ in api.targets} == set(SYMBOLS)
    assert all(s != config().continuous for _, s, _ in api.targets)
    assert frames[-1]['progress']['percent'] == 100
    assert all(f['progress']['percent'] != 100 for f in frames[:-1])
    assert len({e['risk']['trade_id'] for f in frames for e in f['risk_events']
                if e['risk']['trade_id']}) == 1


def test_prewarm_uses_historical_mapping_without_orders(tmp_path):
    fixture = ContinuousSdkFixture()
    result = run(tmp_path, fixture)
    assert result['status'] == 'backtest_finished', result
    start = int(__import__('pandas').Timestamp('2025-01-03', tz='Asia/Shanghai').value)
    assert all(stamp >= start for stamp, _, _ in fixture.apis[0].targets)
    with sqlite3.connect(tmp_path/result['run_id']/'journal.sqlite3') as db:
        raw = dict(db.execute('SELECT * FROM state'))
        assert json.loads(raw['engine_start']) < '2025-01-03'
        assert db.execute('SELECT min(time_ns) FROM signal_bars').fetchone()[0] < start


@pytest.mark.parametrize('fault,reason', [('calendar', 'trading_calendar_unavailable'),
    ('mapping', 'historical_main_missing'), ('reference', 'roll_reference_missing'),
    ('prewarm', 'prewarm_insufficient'), ('multiplier', 'roll_spec_incompatible'),
    ('unaffordable', 'roll_unaffordable'), ('reject', 'order_rejected'),
    ('disconnect', 'connection_lost')])
def test_failures_are_terminal_and_do_not_claim_success(tmp_path, fault, reason):
    fixture = ContinuousSdkFixture(faults={fault})
    frames = []
    result = run(tmp_path, fixture, view_progress=frames.append)
    assert result['status'] != 'backtest_finished'
    assert result['reason'] == reason
    assert fixture.apis[0].closed
    assert all(f['progress']['percent'] != 100 for f in frames)
    assert 'private-' not in json.dumps(result)
    assert set(result['failure_context']) <= {'date', 'symbol', 'data_type'}


def test_tick_denial_keeps_requested_precision(tmp_path):
    fixture = ContinuousSdkFixture(faults={'tick'})
    result = execute_research('backtest', replace(config(), precision='tick'), tmp_path,
        ('u', 'p'), sdk=fixture.sdk)
    assert result['reason'] == 'tick_data_unavailable'


def test_continuous_paper_is_rejected_before_sdk_creation(tmp_path):
    fixture = ContinuousSdkFixture()
    with pytest.raises(ValueError):
        execute_research('paper', config(), tmp_path, ('u', 'p'), sdk=fixture.sdk)
    assert not fixture.calls


def test_session_rejects_continuous_paper_without_starting_thread(tmp_path):
    from qf.research_session import ResearchSession
    session = ResearchSession(tmp_path, execute_fn=lambda *a, **kw: None)
    with pytest.raises(ValueError):
        session.start('paper', config(), ('u', 'p'), experiment_ref={})
    assert session.thread is None


def test_session_whitelists_logical_risk_roll_and_failure_context(tmp_path):
    from qf.research_session import ResearchSession
    session = ResearchSession(tmp_path)
    session._progress('research_state', logical_risk={'floor_gross': '-100', 'password': 'bad'},
        roll={'phase': 'old_exit', 'token': 'bad'},
        failure_context={'date': '2025-01-03', 'symbol': SYMBOLS[0], 'token': 'bad'})
    snapshot = session.snapshot()
    assert snapshot['logical_risk'] == {'floor_gross': '-100'}
    assert snapshot['roll'] == {'phase': 'old_exit'}
    assert 'bad' not in json.dumps(snapshot)


def test_night_session_belongs_to_next_trading_day_and_forming_bar_is_excluded():
    import pandas as pd

    from qf.continuous_runtime import completed_rows, trading_day
    stamp = int(pd.Timestamp('2025-01-02 21:00', tz='Asia/Shanghai').value)
    assert trading_day(stamp) == '2025-01-03'
    frame = pd.DataFrame([dict(datetime=stamp, open=100, high=101, low=99,
                               close=100, volume=1, close_oi=2)])
    assert completed_rows(frame, 60, stamp+59_000_000_000) == []


def test_roll_still_pending_at_replay_end_is_incomplete(tmp_path):
    from continuous_sdk import sample_events
    fixture = ContinuousSdkFixture(sample_events()[:42])
    result = run(tmp_path, fixture)
    assert result['reason'] == 'roll_incomplete_at_end'
    assert result['status'] == 'frozen'


def test_historical_stall_stops_with_context(tmp_path, monkeypatch):
    import itertools

    fixture = ContinuousSdkFixture(faults={'stalled'})
    ticks = itertools.count()
    monkeypatch.setattr('qf.continuous_runtime.time.monotonic', lambda: next(ticks)*.2)
    result = execute_research('backtest', replace(config(), timeout_seconds=5),
        tmp_path, ('u', 'p'), sdk=fixture.sdk)
    assert result['reason'] == 'historical_time_stalled'


@pytest.mark.parametrize('completed', [False, True])
def test_daily_terminal_close_needs_exact_sdk_evidence(tmp_path, completed):
    from types import SimpleNamespace as NS

    import pandas as pd
    from tqsdk.datetime import _convert_user_input_to_nano, _get_trading_day_start_time

    from qf.continuous_journal import ContinuousJournal
    from qf.research_runtime import capture_terminal_close

    cfg = replace(config(), bar_seconds=86400)
    j = ContinuousJournal.create(tmp_path, 'backtest', cfg)
    stamp = int(pd.Timestamp('2025-01-03', tz='Asia/Shanghai').value)
    end = _get_trading_day_start_time(stamp+86400_000_000_000)-1000
    row = dict(id=0, datetime=stamp, open=100, high=101, low=99, close=100,
               volume=10, close_oi=20)
    start_ns, end_ns = _convert_user_input_to_nano(cfg.start, cfg.end)
    bt = NS(_start_dt=start_ns, _end_dt=end_ns, _generators={}, _serials={
        (SYMBOLS[0], 86400_000_000_000): dict(when='CLOSE' if completed else 'OPEN',
                                          timestamp=end, kline_or_tick=row)})
    try:
        result = capture_terminal_close(j, NS(symbol=SYMBOLS[0], bar_seconds=86400),
                                         bt, pd.DataFrame([row]))
        assert (result == end) is completed
        assert j.db.execute('SELECT count(*) FROM research_bars').fetchone()[0] == int(completed)
    finally:
        j.close()
