from dataclasses import replace
from types import SimpleNamespace as NS

import pandas as pd
import pytest
from continuous_sdk import SYMBOLS, ContinuousSdkFixture
from test_continuous_runtime import config
from tqsdk.datetime import _get_trading_day_start_time

from qf.continuous_journal import ContinuousJournal
from qf.continuous_runtime import ContinuousLoop, completed_rows
from qf.research_runtime import execute_research


def daily_row(day, price):
    return dict(datetime=int(pd.Timestamp(day, tz='Asia/Shanghai').value), open=price,
                high=price+1, low=price-1, close=price, volume=10, close_oi=20)


def test_sdk_daily_close_is_usable_only_with_matching_close_evidence():
    row = daily_row('2025-01-03', 100)
    close = _get_trading_day_start_time(row['datetime']+86400_000_000_000)-1000
    bt = NS(_serials={(SYMBOLS[0], 86400_000_000_000): dict(
        when='CLOSE', timestamp=close, kline_or_tick=row)})
    rows = completed_rows(pd.DataFrame([row]), 86400, close, backtest=bt, symbol=SYMBOLS[0])
    assert len(rows) == 1 and rows[0]['completed_at_ns'] == close
    bt._serials[(SYMBOLS[0], 86400_000_000_000)]['when'] = 'OPEN'
    assert completed_rows(pd.DataFrame([row]), 86400, close,
                          backtest=bt, symbol=SYMBOLS[0]) == []


def test_sdk_cursor_already_points_to_next_open_after_close_was_delivered():
    row = daily_row('2025-01-03', 100) | {'id': 0}
    duration = 86400_000_000_000
    close = _get_trading_day_start_time(row['datetime']+duration)-1000
    # SDK 在发送本次 diff 前已经 fetch 下一事件；游标不代表刚发送的事件。
    bt = NS(_current_dt=close, _sended_to_api={(SYMBOLS[0], duration): [(0, 1)]},
        _serials={(SYMBOLS[0], duration): dict(when='OPEN', timestamp=close+86400_000_000_000,
                                            kline_or_tick={'datetime': row['datetime']+duration})})
    assert len(completed_rows(pd.DataFrame([row]), 86400, close,
                              backtest=bt, symbol=SYMBOLS[0])) == 1
    bt._current_dt = close-1
    assert completed_rows(pd.DataFrame([row]), 86400, close-1,
                          backtest=bt, symbol=SYMBOLS[0]) == []


def test_daily_roll_consumes_completed_old_bar_before_switch(tmp_path):
    cfg = replace(config(), bar_seconds=86400)
    fixture = ContinuousSdkFixture()
    account = fixture.sdk.TqSim(init_balance=100000)
    bt = fixture.sdk.TqBacktest(start_dt=cfg.start, end_dt=cfg.end)
    api = fixture.sdk.TqApi(account=account, backtest=bt)
    j = ContinuousJournal.create(tmp_path, 'backtest', cfg)
    now = int(pd.Timestamp('2025-01-06 21:00', tz='Asia/Shanghai').value)
    loop = ContinuousLoop(fixture.sdk, api, account, j, cfg, multiplier=1, start_ns=now+1)
    try:
        evidence = loop.series.switch(old_symbol=None, new_symbol=SYMBOLS[0],
            detected_ns=int(pd.Timestamp('2025-01-02', tz='Asia/Shanghai').value),
            old_rows=[], new_rows=[])
        j.record_mapping(evidence)
        for symbol, price in zip(SYMBOLS[:2], [100, 200], strict=True):
            loop.quotes[symbol] = api.get_quote(symbol)
            loop.serials[symbol] = pd.DataFrame([daily_row('2025-01-03', price)])
            assert loop.ensure_spec(symbol)
        loop.guard.start({}, {}, activate=True)
        loop.step(NS(underlying_symbol=SYMBOLS[1]), now)
        saved = j.db.execute('SELECT source_symbol,time_ns FROM signal_bars').fetchall()
        assert saved == [(SYMBOLS[0], daily_row('2025-01-03', 100)['datetime'])]
    finally:
        j.close()


@pytest.mark.parametrize('reason', ['take_profit', 'initial_stop', 'stair_stop', 'ma_reverse'])
def test_normal_risk_exit_during_roll_continues_backtest(tmp_path, monkeypatch, reason):
    from qf.continuous_runtime import ContinuousLoop

    original = ContinuousLoop.protect
    fired = []
    def protect(loop, positions):
        original(loop, positions)
        if loop.roll.state.phase == 'old_exit' and not fired:
            loop.risk = replace(loop.risk, exit_reason=reason)
            fired.append(True)
    monkeypatch.setattr(ContinuousLoop, 'protect', protect)
    fixture = ContinuousSdkFixture()
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=fixture.sdk)
    assert fired
    assert result['status'] == 'backtest_finished', result
    assert result['summary']['closed_trade_count'] >= 1
    assert fixture.apis[0].index == len(fixture.events)-1


def test_second_mapping_is_cleaned_before_recording_a_new_mapping(tmp_path):
    from continuous_sdk import sample_events

    events = sample_events()
    for event in events[41:60]:
        event['symbol'] = SYMBOLS[2]
    fixture = ContinuousSdkFixture(events)
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=fixture.sdk)
    assert result['reason'] == 'roll_mapping_changed', result
    assert all(p.pos_long == p.pos_short == 0 for p in fixture.apis[0].positions.values())
    assert not any(symbol == SYMBOLS[2] and volume for _, symbol, volume in fixture.apis[0].targets)


def test_stop_during_new_entry_advances_until_exit_confirmed(tmp_path):
    fixture = ContinuousSdkFixture()
    def stop():
        return fixture.apis and fixture.apis[0].index >= 44
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=fixture.sdk,
                              stop_requested=stop)
    assert result['status'] == 'stopped', result
    assert all(p.pos_long == p.pos_short == 0 for p in fixture.apis[0].positions.values())
    assert fixture.apis[0].index >= 46
    import sqlite3
    with sqlite3.connect(tmp_path/result['run_id']/'journal.sqlite3') as db:
        assert db.execute('SELECT reason FROM logical_trades').fetchone()[0] == 'stop_requested'
        raw = db.execute("SELECT risk FROM risk_events WHERE kind='fill' "
                         "ORDER BY time_ns DESC LIMIT 1").fetchone()[0]
        assert __import__('json').loads(raw)['exit_reason'] == 'stop_requested'


def test_late_open_fill_keeps_order_role_until_cancel_confirmation(tmp_path):
    from continuous_sdk import sample_events

    events = sample_events()
    for event in events[28:40]:
        event['price'] = 94
    fixture = ContinuousSdkFixture(events, faults={'late_cancel'})
    cfg = replace(config(), risk=replace(config().risk, fixed_lots=3))
    result = execute_research('backtest', cfg, tmp_path, ('u', 'p'), sdk=fixture.sdk)
    assert result['status'] == 'backtest_finished', result
    trades = list(fixture.apis[0].trades.values())
    first_open = trades[0].order_id
    assert sum(t.volume for t in trades if t.order_id == first_open) == 3
    assert sum(t.volume for t in trades if t.offset == 'CLOSE') >= 3
    import sqlite3
    with sqlite3.connect(tmp_path/result['run_id']/'journal.sqlite3') as db:
        roles = db.execute('SELECT DISTINCT l.role FROM logical_fills l JOIN fills f '
                           'ON f.key=l.fill_key WHERE f.order_id=?', (first_open,)).fetchall()
        assert roles == [('strategy_open',)]
