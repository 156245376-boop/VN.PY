from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace as NS

import pandas as pd
import pytest
from continuous_sdk import SYMBOLS, ContinuousSdkFixture
from test_continuous_runtime import config

from qf.continuous_journal import ContinuousJournal
from qf.continuous_risk import LogicalRisk
from qf.continuous_roll import RollState
from qf.continuous_runtime import ContinuousLoop
from qf.ma_cross import CrossSignal
from qf.pivot_stop import Pivot
from qf.research_contract import make_target_task
from qf.trade_risk import ContractSpec


def test_target_supports_sdk_minimum_open_volume():
    calls = []

    class Target:
        def __init__(self, api, symbol, **kwargs):
            calls.append((api, symbol, kwargs))

    api = object()
    sdk = type('Sdk', (), {'TargetPosTask': Target})()
    quote = type('Quote', (), {
        'open_min_limit_order_volume': 5,
        'open_min_market_order_volume': 1,
    })()

    make_target_task(sdk, api, SYMBOLS[0], quote)

    assert len(calls) == 1
    assert calls[0][:2] == (api, SYMBOLS[0])
    assert calls[0][2]['offset_priority'] == '今,昨,开'
    assert calls[0][2]['support_open_min_volume'] is True


def _rows(closes, *, day='2025-01-03'):
    base = int(pd.Timestamp(day+' 09:00:00', tz='Asia/Shanghai').value)
    minute = 60_000_000_000
    return [dict(datetime=base+i*minute, end_ns=base+(i+1)*minute,
                 open=price, high=price+1, low=price-1, close=price,
                 volume=10, close_oi=20, completed=True)
            for i, price in enumerate(closes)]


def _loop(tmp_path):
    cfg = replace(config(), fast_period=2, slow_period=3,
                  risk=replace(config().risk, pivot_left=1, pivot_right=1,
                               stairs_enabled=False))
    fixture = ContinuousSdkFixture()
    account = fixture.sdk.TqSim(init_balance=100000)
    backtest = fixture.sdk.TqBacktest(start_dt=cfg.start, end_dt=cfg.end)
    api = fixture.sdk.TqApi(account=account, backtest=backtest)
    journal = ContinuousJournal.create(tmp_path, 'backtest', cfg)
    loop = ContinuousLoop(fixture.sdk, api, account, journal, cfg,
                          multiplier=1, start_ns=0)
    evidence = loop.series.switch(old_symbol=None, new_symbol=SYMBOLS[0],
        detected_ns=_rows([100])[0]['datetime'], old_rows=[], new_rows=[])
    journal.record_mapping(evidence)
    return loop, journal


def test_batch_prefix_cross_is_recorded_without_late_entry(tmp_path):
    loop, journal = _loop(tmp_path)
    rows = _rows([103, 102, 101, 104, 105])
    loop.start_ns = rows[0]['datetime']
    loop.now = rows[-1]['end_ns']
    try:
        signal = loop.consume(SYMBOLS[0], rows)

        assert signal is None
        events = journal.db.execute(
            'SELECT payload FROM risk_events WHERE kind=? ORDER BY time_ns',
            ('skipped',)).fetchall()
        payloads = [__import__('json').loads(row[0]) for row in events]
        assert any(item.get('reason') == 'historical_signal_superseded'
                   for item in payloads)
        assert not any(item.get('reason') == 'warmup_signal_ignored'
                       for item in payloads)
    finally:
        journal.close()


def test_warmup_prefix_cannot_become_start_day_entry(tmp_path):
    loop, journal = _loop(tmp_path)
    rows = _rows([103, 102, 101, 104, 105])
    loop.start_ns = rows[2]['datetime'] + 1
    loop.now = rows[-1]['end_ns']
    try:
        assert loop.consume(SYMBOLS[0], rows) is None
    finally:
        journal.close()


def _reverse_loop(tmp_path):
    loop, journal = _loop(tmp_path)
    symbol = SYMBOLS[0]
    base = _rows([100])[0]['datetime']
    loop.now, loop.start_ns, loop.prewarmed = base+60_000_000_000, base, True
    loop.risk = LogicalRisk('trade-1', 1, 1, Decimal('3301'), Decimal('850'),
                            True, 0, Decimal('-850'), Decimal('0'), Decimal('0'),
                            Decimal('10'), None, base-1, base-1)
    loop.specs[symbol] = ContractSpec(symbol, Decimal(1), Decimal(10), 1, 1,
                                     Decimal(1000), Decimal(2), 'fixture')
    loop.quotes[symbol] = NS(symbol=symbol, last_price=3200, bid_price1=3200,
                             ask_price1=3200, price_tick=1, volume_multiple=10)
    loop.pivots[-1] = Pivot('high', Decimal('3400'), base-120_000_000_000,
                            base-60_000_000_000, 1, 1)
    positions = {symbol: (1, 0)}
    loop.reconcile = lambda execute_deferred=True: (positions, False)
    loop.protect = lambda value: None
    loop.subscribe = lambda value: loop.quotes[value]
    loop.ensure_spec = lambda value: True
    loop.closed_rows = lambda value, now: []
    targets = []
    loop.target = lambda value, volume, role: targets.append((volume, role))
    return loop, journal, targets, symbol, base


def test_confirmed_reverse_survives_exit_confirmation(tmp_path):
    loop, journal, targets, symbol, base = _reverse_loop(tmp_path)
    signals = [CrossSignal(base, base+60_000_000_000, -1, 104, 103, 100, 102), None]
    loop.consume = lambda value, rows: signals.pop(0)
    try:
        loop.step(NS(underlying_symbol=symbol), base+60_000_000_000)
        assert targets == [(0, 'strategy_close')]
        assert loop.pending_reverse is not None

        loop.risk = replace(loop.risk, quantity=0)
        loop.step(NS(underlying_symbol=symbol), base+120_000_000_000)

        assert targets == [(0, 'strategy_close'), (-1, 'strategy_open')]
        assert loop.pending_reverse is None
    finally:
        journal.close()


@pytest.mark.parametrize('mode', ['stop', 'roll'])
def test_pending_reverse_is_cancelled_by_stop_or_roll(tmp_path, monkeypatch, mode):
    loop, journal, targets, symbol, base = _reverse_loop(tmp_path)
    signal = CrossSignal(base, base+60_000_000_000, -1, 104, 103, 100, 102)
    pivot = loop.pivots[-1]
    loop.pending_reverse = (signal, pivot)
    advanced = []
    monkeypatch.setattr(loop, 'advance_roll',
        lambda positions, **kw: advanced.append(kw))
    if mode == 'roll':
        loop.roll.state = RollState('old_cancel', symbol, SYMBOLS[1], 0, 0,
                                    base, None)
        main = NS(underlying_symbol=symbol)
    else:
        main = NS(underlying_symbol=symbol)
    try:
        loop.step(main, base+60_000_000_000, stopping=mode == 'stop')
        assert loop.pending_reverse is None
        assert targets == []
    finally:
        journal.close()
