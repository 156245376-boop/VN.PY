import copy
import json
import sqlite3
import threading
from dataclasses import replace

import pandas as pd
from pivot_sdk import PivotApi, sdk_for_pivot
from test_pivot_runtime import config

from qf.research_journal import ResearchJournal
from qf.research_runtime import execute_research
from qf.research_session import ResearchSession


def business(root, run):
    with sqlite3.connect(root/run/'journal.sqlite3') as db:
        events = []
        trades = {}
        for stamp, kind, payload, risk, target in db.execute(
                'SELECT time_ns,kind,payload,risk,target FROM risk_events ORDER BY rowid'):
            state = json.loads(risk)
            if state['trade_id']:
                state['trade_id'] = trades.setdefault(state['trade_id'], len(trades)+1)
            events.append([stamp, kind, json.loads(payload), state, target])
        return dict(events=events, fills=list(db.execute('SELECT * FROM fills ORDER BY rowid')),
                    equity=list(db.execute('SELECT * FROM equity ORDER BY time_ns')))


def test_view_toggle_does_not_change_strategy_execution(tmp_path):
    outputs, subscriptions = [], []
    for watch in (False, True):
        frames = []
        def callback(frame, dest=frames):
            dest.append(copy.deepcopy(frame))
        result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
            sdk=sdk_for_pivot(), view_progress=callback if watch else None)
        assert result['status'] == 'backtest_finished'
        outputs.append(business(tmp_path, result['run_id']))
        subscriptions.append(PivotApi.instances[-1].subscriptions)
        if watch:
            assert frames[-1]['progress']['percent'] == 100
    assert outputs[0] == outputs[1] and subscriptions[0] == subscriptions[1]


def test_new_job_clears_previous_plan_and_failure(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def execute(*a, **kw):
        entered.set()
        release.wait(3)
        return dict(status='stopped')
    session = ResearchSession(tmp_path, execute_fn=execute)
    session._state.update(entry_plan={'stop_price': '99'}, reason='order_rejected', equity='123')
    try:
        session.start('backtest', config(), ('u', 'p'), experiment_ref={})
        assert entered.wait(2)
        assert session.snapshot()['entry_plan'] is None
        assert session.snapshot()['reason'] is None and session.snapshot()['equity'] is None
    finally:
        release.set()
        session.thread.join(3)


def test_known_expiry_is_checked_before_backtest(tmp_path):
    sdk = sdk_for_pivot()
    class Expiring(PivotApi):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.quote.expire_datetime = pd.Timestamp('2025-03-02', tz='Asia/Shanghai').timestamp()
    sdk.TqApi = Expiring
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk)
    assert result['reason'] == 'contract_range_exceeds_expiry'
    assert not PivotApi.instances[-1].targets


def test_paper_has_no_fictional_time_percentage(tmp_path):
    values = []
    sdk = sdk_for_pivot()
    result = execute_research('paper', config(), tmp_path, ('u', 'p'), sdk=sdk,
        stop_requested=lambda: PivotApi.instances[-1].steps >= 1,
        progress=lambda stage, **fields: values.append(fields.get('details')))
    assert result['status'] == 'stopped'
    assert values and all(p['percent'] is None for p in values if p)


def test_no_trading_day_and_independent_double_fee_progress(tmp_path):
    weekend = replace(config(), start=config().start.replace(day=8),
                      end=config().end.replace(day=9))
    empty = execute_research('backtest', weekend, tmp_path, ('u', 'p'), sdk=sdk_for_pivot())
    assert empty['reason'] == 'no_trading_days'
    fees = []
    for multiplier in (1, 2):
        frames = []
        result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
            sdk=sdk_for_pivot(), fee_multiplier=multiplier, view_progress=frames.append)
        assert frames[-1]['progress']['percent'] == 100
        journal = ResearchJournal(tmp_path/result['run_id'])
        fees.append(float(journal.get('total_commission')))
        journal.close()
    assert fees[1] == fees[0]*2


def test_new_fill_with_stale_quote_remains_visible_in_committed_snapshot(tmp_path):
    sdk = sdk_for_pivot()
    class Lagging(PivotApi):
        def wait_update(self, **kw):
            result = super().wait_update(**kw)
            self.quote.datetime = '2025-03-03 09:05:00.000000'
            return result
    sdk.TqApi = Lagging
    frames = []
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'),
                              sdk=sdk, view_progress=frames.append)
    records = business(tmp_path, result['run_id'])['fills']
    assert records and len(frames[-1]['fills']) == len(records)
    assert int(frames[-1]['as_of_ns']) >= max(row[-1] for row in records)


def test_no_signal_still_advances_real_time_progress(tmp_path):
    sdk = sdk_for_pivot()
    class Flat(PivotApi):
        def __init__(self, **kw):
            super().__init__(**kw)
            for name in ('open', 'high', 'low', 'close'):
                self.serial[name] = 1000.
    sdk.TqApi = Flat
    records = []
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk,
        progress=lambda stage, **fields: records.append(fields.get('details')))
    advancing = [v['current_ns'] for v in records if v and v['current_ns'] is not None]
    assert result['status'] == 'backtest_finished' and not PivotApi.instances[-1].targets
    assert len(set(advancing)) > 1


def test_pending_reverse_keeps_signal_pivot_when_later_pivot_exists(tmp_path):
    from decimal import Decimal

    from qf.pivot_stop import Pivot
    from qf.research_runtime import ResearchLoop, contract_spec, quote_ns
    sdk = sdk_for_pivot()
    api, account, cfg = sdk.TqApi(), sdk.TqSim(), config()
    serial = api.get_kline_serial(cfg.symbol, cfg.bar_seconds)
    journal = ResearchJournal.create(tmp_path, 'backtest', cfg.public())
    loop = ResearchLoop(sdk, api, account, journal, cfg,
        contract_spec(api, account, cfg.symbol, api.quote, paper=False, multiplier=1),
        paper=False, active=True, progress=None)
    loop.guard.start({}, {}, activate=True)
    api.execution_guard = loop.guard
    now = quote_ns(api.quote)
    old = Pivot('low', Decimal('995'), now-900_000_000_000, now-1, 2, 2)
    loop.pending_pivot = old
    loop.pivots[1] = Pivot('low', Decimal('990'), now-600_000_000_000, now, 2, 2)
    loop.pending_direction, loop.phase = 1, 'exiting'
    loop.last_bar = int(serial.iloc[-2].datetime)
    try:
        loop.step(api.quote, serial, minimum_bar=0, start_ns=0, end_ns=2**63-1, flatten=False)
        assert api.targets == [16] and loop.entry_plan.pivot == old
    finally:
        journal.close()
