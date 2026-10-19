import threading
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace as NS

import pandas as pd
from pivot_sdk import PivotApi, sdk_for_pivot
from test_pivot_runtime import config
from test_trade_risk import inputs
from tqsdk.backtest import TqBacktest
from tqsdk.datetime import _convert_user_input_to_nano, _get_trading_day_start_time

from qf.pivot_stop import Pivot, plan_pivot_entry
from qf.research_journal import ResearchJournal
from qf.research_runtime import execute_research
from qf.research_session import ResearchSession


def test_real_sdk_fractional_tick_tail_does_not_skip_legal_entry():
    symbol = 'SHFE.rb2505'
    item = dict(open=3840.2, high=3840.2, low=3840.2, close=3840.2, close_oi=1)
    quote = TqBacktest._get_quote_diffs_from_kline(symbol, .2, 1740963900000000000,
                                                 item, ['close'])[0]['quotes'][symbol]
    spec = replace(inputs()[1], price_tick=Decimal('.2'), volume_multiple=Decimal(300))
    risk = replace(config().risk, risk_budget=Decimal(10000))
    pivot = Pivot('low', Decimal(3830), 1, 2, 2, 2)
    def plan(price):
        return plan_pivot_entry(risk, spec, side=1, reference_price=Decimal(str(price)),
            pivot=pivot, available=Decimal(100000), startup_equity=Decimal(100000))
    actual, canonical = plan(quote['ask_price1']), plan('3840.4')
    assert actual == canonical and actual.lots == 3
    assert plan('3840.41').reason == 'stop_off_tick'


def test_waiting_clock_moves_without_fabricating_history_progress(tmp_path, monkeypatch):
    clock = [10.]
    monkeypatch.setattr('qf.research_session.time.monotonic', lambda: clock[0])
    entered, release = threading.Event(), threading.Event()
    def execute(*a, **kw):
        kw['progress']('research_progress', details=dict(stage='connecting', current_ns=None,
            percent=None, completed_bars=0, fill_count=0, elapsed_seconds=0,
            last_advance_age_seconds=0, finished=False))
        entered.set()
        release.wait(3)
        return dict(status='stopped')
    session = ResearchSession(tmp_path, execute_fn=execute)
    try:
        session.start('backtest', config(), ('u', 'p'), experiment_ref={})
        assert entered.wait(2)
        clock[0] = 22.
        state = session.snapshot()['progress']
        assert state['elapsed_seconds'] == state['last_advance_age_seconds'] == 12
        assert state['percent'] is None and state['current_ns'] is None
    finally:
        release.set()
        session.thread.join(3)


def daily_sdk(*, complete):
    sdk = sdk_for_pivot()
    period = 86400_000_000_000
    stamp = int(pd.Timestamp('2025-03-03', tz='Asia/Shanghai').value)
    close_ns = _get_trading_day_start_time(stamp+period)-1000
    class Daily(PivotApi):
        def get_kline_serial(self, symbol, duration, **kw):
            if duration != 86400:
                return super().get_kline_serial(symbol, duration, **kw)
            self.subscriptions.append(('kline', duration))
            self.serial['datetime'] = [int(day.value) for day in pd.bdate_range(
                end='2025-03-03', periods=len(self.serial), tz='Asia/Shanghai')]
            return self.serial

        def wait_update(self, **kw):
            backtest = self.kwargs['backtest']
            row = self.serial.iloc[-1].to_dict()
            backtest._serials = {(config().symbol, period): dict(
                when='CLOSE' if complete else 'OPEN', timestamp=close_ns,
                kline_or_tick=row)}
            backtest._generators = {}
            backtest._current_dt = 2145888000000000000
            raise sdk.BacktestFinished()
    sdk.TqApi = Daily
    def backtest(**kw):
        first, last = _convert_user_input_to_nano(kw['start_dt'], kw['end_dt'])
        return NS(_start_dt=first, _end_dt=last, _current_dt=first,
                  _serials={}, _generators={})
    sdk.TqBacktest = backtest
    return sdk


def test_last_daily_close_is_coverage_without_replaying_a_terminal_signal(tmp_path):
    cfg = replace(config(), bar_seconds=86400)
    frames = []
    result = execute_research('backtest', cfg, tmp_path, ('u', 'p'),
                              sdk=daily_sdk(complete=True), view_progress=frames.append)
    assert result['status'] == 'backtest_finished'
    journal = ResearchJournal(tmp_path/result['run_id'])
    try:
        evidence = journal.get('terminal_close_bar')
        assert evidence['signal_consumed'] is False
        assert journal.get('coverage_check')['status'] == 'verified'
        assert not PivotApi.instances[-1].targets
        assert frames[-1]['bars'][-1]['completed'] is True
        assert frames[-1]['bars'][-1]['signal_consumed'] is False
    finally:
        journal.close()
    incomplete = execute_research('backtest', cfg, tmp_path, ('u', 'p'),
                                  sdk=daily_sdk(complete=False))
    assert incomplete['reason'] == 'historical_coverage_incomplete'
