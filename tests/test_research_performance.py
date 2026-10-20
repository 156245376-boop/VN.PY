import pandas as pd
import pytest
from continuous_sdk import SYMBOLS, ContinuousSdkFixture
from pivot_sdk import sdk_for_pivot
from research_helpers import pivot_config_data
from test_continuous_runtime import config as continuous_config

from qf.continuous_journal import ContinuousJournal
from qf.continuous_runtime import ContinuousLoop
from qf.research_config import validate_research_config
from qf.research_runtime import execute_research
from qf.research_view import ViewDemand
from qf.safety import Frozen


def _loop(tmp_path):
    cfg = continuous_config()
    fixture = ContinuousSdkFixture()
    account = fixture.sdk.TqSim(init_balance=100000)
    backtest = fixture.sdk.TqBacktest(start_dt=cfg.start, end_dt=cfg.end)
    api = fixture.sdk.TqApi(account=account, backtest=backtest)
    journal = ContinuousJournal.create(tmp_path, 'backtest', cfg)
    loop = ContinuousLoop(fixture.sdk, api, account, journal, cfg,
                          multiplier=1, start_ns=0)
    return loop, journal, backtest, fixture


def test_duplicate_updates_do_not_reappend_history(tmp_path):
    loop, journal, backtest, fixture = _loop(tmp_path)
    base = int(pd.Timestamp('2025-01-03 09:00', tz='Asia/Shanghai').value)
    rows = [dict(datetime=base+i*60_000_000_000, open=100+i, high=101+i,
                 low=99+i, close=100+i, volume=10, close_oi=20)
            for i in range(3)]
    loop.serials[SYMBOLS[0]] = pd.DataFrame(rows)
    now = base+3*60_000_000_000
    try:
        first = loop.closed_rows(SYMBOLS[0], now)
        second = loop.closed_rows(SYMBOLS[0], now)
        assert len(first) == 3 and second == []
        loop.serials[SYMBOLS[0]].loc[0, 'close'] = 99
        with pytest.raises(Frozen, match='historical_data_invalid'):
            loop.closed_rows(SYMBOLS[0], now)
    finally:
        journal.close()


def test_view_demand_is_thread_safe_switch():
    demand = ViewDemand()
    assert demand.wants_frame() is False
    demand.set(True, 2)
    assert demand.snapshot() == (True, 2)
    demand.set(False, 3)
    assert demand.wants_frame() is False


def test_fast_and_watch_switches_gate_frames(tmp_path):
    raw = pivot_config_data()
    raw['end'] = raw['start']
    config = validate_research_config(raw)
    fast_frames = []
    watch_frames = []
    fast = execute_research('backtest', config, tmp_path/'fast', ('u', 'p'),
                            sdk=sdk_for_pivot(),
                            view_progress=fast_frames.append,
                            view_requested=lambda: False)
    watched = execute_research('backtest', config, tmp_path/'watch', ('u', 'p'),
                               sdk=sdk_for_pivot(),
                               view_progress=watch_frames.append,
                               view_requested=lambda: True)
    assert fast['status'] == watched['status'] == 'backtest_finished'
    assert fast_frames == []
    assert watch_frames
