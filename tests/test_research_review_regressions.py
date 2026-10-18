import sqlite3
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest
from research_sdk import BASE, Api, sdk_for
from test_research_runtime import config
from test_trade_risk import entered, inputs

from qf.replay_view import ReplayView
from qf.research_journal import ResearchJournal
from qf.research_results import read_run, run_details
from qf.research_runtime import ResearchLoop, execute_research


def setup_loop(tmp_path, *, paper=False, minimum=1):
    sdk = sdk_for()
    api = Api(account=sdk.TqSim())
    cfg = config()
    _, spec = inputs()
    spec = replace(spec, min_open_lots=minimum)
    j = ResearchJournal.create(tmp_path, 'paper' if paper else 'backtest', cfg.public())
    loop = ResearchLoop(sdk, api, api.kwargs['account'], j, cfg, spec,
                        paper=paper, active=True, progress=None)
    loop.guard.start({}, {}, activate=True)
    api.execution_guard = loop.guard
    return loop, api, j


def step(loop, api):
    loop.step(api.quote, api.serial, minimum_bar=0, start_ns=0, end_ns=2**63-1,
              flatten=False)


def test_split_quote_and_bar_retry_and_block_true_completion_time(tmp_path):
    loop, api, j = setup_loop(tmp_path)
    try:
        api.quote.datetime = '2025-03-03 09:04:59'
        step(loop, api)
        assert api.targets == []
        api.quote.datetime = '2025-03-03 09:05:01'
        step(loop, api)
        assert api.targets == [2]
    finally:
        j.close()
    loop, api, j = setup_loop(tmp_path)
    try:
        loop.block_before = BASE + 310_000_000_000
        api.quote.datetime = '2025-03-03 09:05:11'
        step(loop, api)
        assert api.targets == []
    finally:
        j.close()


def test_legal_below_minimum_remainder_seals_actual_risk(tmp_path, monkeypatch):
    loop, api, j = setup_loop(tmp_path, minimum=5)
    try:
        loop.risk = entered(quantity=4)
        loop.phase, loop.target = 'entering', 5
        loop.new_task()
        loop.pending_since = 1
        monkeypatch.setattr('qf.research_runtime.time.monotonic', lambda: 32)
        loop.reconcile_task(BASE, {})
        assert loop.phase == 'holding'
        assert loop.risk.quantity == 4 and loop.risk.sealed
        assert loop.target == 4 and loop.pending_since is None
        assert j.get('last_target') == 4
    finally:
        j.close()


def test_stale_day_cannot_duplicate_fees_or_overwrite_old_equity(tmp_path):
    loop, api, j = setup_loop(tmp_path, paper=True)
    try:
        for timestamp, fee in [('2025-03-03 09:00', 0), ('2025-03-03 14:00', 4),
                               ('2025-03-04 09:00', 2), ('2025-03-03 14:00', 2),
                               ('2025-03-04 09:00:01', 2)]:
            api.account.commission = fee
            loop.equity(int(pd.Timestamp(timestamp, tz='Asia/Shanghai').value))
        assert loop.total_fee == Decimal(6)
        assert j.db.execute('SELECT count(*) FROM equity').fetchone()[0] == 4
        prior = j.db.execute(
            'SELECT commission FROM equity ORDER BY time_ns LIMIT 1 OFFSET 1').fetchone()[0]
        assert prior == 4
    finally:
        j.close()


def test_exit_fill_has_its_own_risk_despite_later_flat_confirmation(tmp_path):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for())
    details = run_details(tmp_path, result['run_id'])
    closing = next(f for f in details['fills'] if f['offset'] == 'CLOSE')
    event = next(e for e in details['risk_events']
                 if closing['key'] in e['payload'].get('fill_keys', []))
    assert event['risk']['exit_reason'] == 'stair_stop'
    assert Decimal(event['risk']['initial_r']) == 1000


@pytest.mark.parametrize('corruption', ['bar', 'risk_state', 'risk_events', 'fill_link'])
def test_incomplete_evidence_is_rejected_without_reconstruction(tmp_path, corruption):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for())
    path = tmp_path / result['run_id'] / 'journal.sqlite3'
    with sqlite3.connect(path) as db:
        if corruption == 'bar':
            db.execute('DELETE FROM research_bars WHERE time_ns=(SELECT time_ns '
                       'FROM research_bars ORDER BY time_ns LIMIT 1 OFFSET 3)')
        elif corruption == 'risk_state':
            db.execute("DELETE FROM state WHERE key='risk_state'")
        elif corruption == 'fill_link':
            db.execute("UPDATE risk_events SET payload='{}' WHERE kind='fill'")
        else:
            db.execute('DELETE FROM risk_events')
    with pytest.raises(ValueError):
        read_run(tmp_path, result['run_id'])
    view = ReplayView(tmp_path)
    try:
        with pytest.raises(ValueError):
            view.open(result['run_id'])
    finally:
        view.close()
