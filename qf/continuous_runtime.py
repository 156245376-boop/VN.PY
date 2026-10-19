"""一个 SDK 历史会话、一个资金账户，按当时映射串行移仓。"""

import math
import re
import time
import uuid
from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
from tqsdk.datetime import _convert_user_input_to_nano, _get_trading_day_from_timestamp

from qf.continuous_journal import ContinuousJournal
from qf.continuous_results import continuous_snapshot, summarize_continuous_run
from qf.continuous_risk import (
    LogicalRisk,
    apply_logical_fill,
    logical_stop,
    protect_logical,
    seal_logical,
)
from qf.continuous_roll import ContinuousGuard, RollCoordinator, RollState
from qf.continuous_series import SignalSeries
from qf.ma_cross import completed_cross_closed
from qf.pivot_stop import latest_confirmed_pivot, plan_pivot_entry
from qf.research_config import decimal_value as dec
from qf.research_config import public_values
from qf.research_contract import contract_spec
from qf.research_coverage import assess_coverage
from qf.research_journal import bar_end_ns
from qf.research_progress import BacktestProgress
from qf.runtime import (
    check_connections,
    emit_progress,
    positions_snapshot,
    provenance,
    tracked_api,
    trades_snapshot,
)
from qf.safety import Frozen


def trading_day(stamp):
    return str(pd.Timestamp(_get_trading_day_from_timestamp(stamp), tz='UTC')
               .tz_convert('Asia/Shanghai').date())


def completed_rows(serial, period, now):
    rows = []
    for raw in serial.to_dict('records'):
        if not raw.get('datetime') or raw['datetime'] <= 0:
            continue
        stamp = int(raw['datetime'])
        end = bar_end_ns(stamp, period)
        if end <= now:
            row = {k: raw[k] for k in ('open', 'high', 'low', 'close', 'volume', 'close_oi')}
            rows.append(row | dict(datetime=stamp, end_ns=end, completed=True))
    if any(a['datetime'] >= b['datetime'] for a, b in zip(rows, rows[1:], strict=False)):
        raise Frozen('historical_data_invalid')
    return rows


class ContinuousLoop:
    def __init__(self, sdk, api, account, journal, config, *, multiplier, start_ns):
        self.sdk, self.api, self.account, self.j = sdk, api, account, journal
        self.config, self.multiplier, self.start_ns = config, multiplier, start_ns
        self.risk = LogicalRisk()
        self.roll = RollCoordinator(RollState(), timeout_seconds=config.execution_timeout_seconds)
        self.guard = ContinuousGuard(journal, self.roll, fill_handler=self.accept_fill)
        self.series = SignalSeries(config.bar_seconds,
            max_window=max(config.slow_period+2, config.risk.pivot_left+config.risk.pivot_right+2))
        self.quotes, self.serials, self.specs = {}, {}, {}
        self.tasks, self.targets, self.roles, self.cancelled = {}, {}, {}, set()
        self.entry_plan, self.pending_mapping = None, None
        self.now, self.last_signal, self.intent_since = 0, 0, None
        self.prewarmed = False
        self.roll_clock = 0
        self.pivots = {1: None, -1: None}
        self.observed, self.captured = set(), {}
        self.context = dict(date=str(config.start), symbol=config.continuous, data_type='mapping')

    def record(self, kind, payload=None, target=None):
        self.j.commit_continuous(uuid.uuid4().hex, time_ns=self.now, kind=kind,
            payload=payload or {}, logical_risk=self.risk, roll_state=asdict(self.roll.state),
            fills=[], target=target)

    def accept_fill(self, fill):
        if self.j.has_fill(fill):
            return
        symbol = fill['symbol']
        role = self.roles.get(symbol)
        if role is None or symbol not in self.specs:
            raise Frozen('fill_intent_missing')
        risk = apply_logical_fill(self.risk, fill, role=role, spec=self.specs[symbol],
            entry_plan=self.entry_plan, risk=self.config.risk)
        if self.j.commit_continuous('fill-'+uuid.uuid4().hex, time_ns=fill['time_ns'], kind='fill',
            payload=dict(role=role, symbol=symbol), logical_risk=risk,
            roll_state=asdict(self.roll.state), fills=[fill]):
            self.risk = risk

    def subscribe(self, symbol):
        if symbol not in self.quotes:
            if not re.fullmatch(re.escape(self.config.continuous[5:])+r'\d{3,4}', symbol):
                raise Frozen('historical_main_invalid')
            self.context.update(symbol=symbol, data_type='kline')
            self.quotes[symbol] = self.api.get_quote(symbol)
            self.serials[symbol] = self.api.get_kline_serial(symbol, self.config.bar_seconds,
                data_length=max(200, self.series.maximum+2))
            if self.config.precision == 'tick':
                try:
                    self.api.get_tick_serial(symbol, data_length=2)
                except Exception:
                    raise Frozen('tick_data_unavailable') from None
            else:
                self.api.get_kline_serial(symbol, 60, data_length=2)
        return self.quotes[symbol]

    def ensure_spec(self, symbol):
        if symbol not in self.specs:
            quote = self.quotes[symbol]
            if not math.isfinite(quote.last_price):
                return False
            spec = contract_spec(self.api, self.account, symbol, quote, paper=False,
                                 multiplier=self.multiplier)
            if self.risk.quantity and self.specs:
                old = self.specs[self.series.symbol]
                if spec.volume_multiple != old.volume_multiple:
                    raise Frozen('roll_spec_incompatible')
            self.j.record_spec(symbol, spec)
            self.specs[symbol] = spec
        return True

    def capture(self, symbol, rows):
        fresh = [r for r in rows if r['datetime'] > self.captured.get(symbol, 0)]
        if fresh:
            self.j.capture_actual(symbol, self.config.bar_seconds, fresh)
            self.captured[symbol] = fresh[-1]['datetime']

    def cancel(self, symbol):
        task = self.tasks.get(symbol)
        if task is not None and symbol not in self.cancelled:
            task.cancel()
            self.cancelled.add(symbol)

    def task_done(self, symbol):
        return symbol not in self.tasks or self.tasks[symbol].is_finished()

    def target(self, symbol, volume, role):
        if volume and role == 'roll_in':
            spec = self.specs[symbol]
            if (abs(volume) < spec.min_open_lots or abs(volume) % spec.lot_step):
                raise Frozen('roll_spec_incompatible')
            if dec(self.api.get_account().available) < spec.margin_per_lot*abs(volume):
                raise Frozen('roll_unaffordable')
        self.roles[symbol] = role
        self.guard.authorize_target(symbol, volume)
        self.record('intent', dict(target_symbol=symbol, role=role), target=volume)
        if self.task_done(symbol):
            self.tasks[symbol] = self.sdk.TargetPosTask(self.api, symbol)
            self.cancelled.discard(symbol)
        self.targets[symbol] = volume
        self.tasks[symbol].set_target_volume(volume)
        self.intent_since = time.monotonic()

    def reconcile(self):
        for fill in trades_snapshot(self.api.get_trade()):
            self.guard.accept_fill(fill)
        positions = positions_snapshot(self.api.get_position())
        self.guard.check(positions, self.api.get_order())
        pending = any(o.status != 'FINISHED' for o in self.api.get_order().values())
        for symbol, target in self.targets.items():
            long, short = positions.get(symbol, (0, 0))
            if long-short == target and not pending:
                self.cancel(symbol)
        if (self.entry_plan is not None and not self.risk.sealed and self.risk.quantity
                and self.risk.quantity == self.entry_plan.lots and not pending
                and self.task_done(self.series.symbol)):
            self.risk = seal_logical(self.risk)
            self.record('sealed', dict(symbol=self.series.symbol))
        return positions, pending

    def protect(self, positions):
        held = next((symbol for symbol, pair in positions.items() if any(pair)), None)
        if held is not None:
            quote, spec = self.quotes[held], self.specs[held]
            self.risk = protect_logical(self.risk, price=dec(quote.last_price), time_ns=self.now,
                                        risk=self.config.risk, spec=spec)
            previous = self.j.get('logical_risk')
            if public_values(asdict(self.risk)) != previous:
                self.record('protection', dict(symbol=held, price=dec(quote.last_price),
                                              quote_ns=self.now))

    def step(self, main, now, *, stopping=False):
        self.now = now
        self.context['date'] = trading_day(now)
        positions, pending = self.reconcile()
        self.protect(positions)
        mapped = main.underlying_symbol
        if not mapped:
            raise Frozen('historical_main_missing')
        self.subscribe(mapped)
        if not self.ensure_spec(mapped):
            return
        if mapped != self.series.symbol and self.pending_mapping is None:
            self.pending_mapping = (mapped, now)
        if self.pending_mapping:
            new, detected = self.pending_mapping
            if new != mapped:
                raise Frozen('roll_mapping_changed')
            old = self.series.symbol
            old_rows = (completed_rows(self.serials[old], self.config.bar_seconds, detected)
                        if old else [])
            new_rows = completed_rows(self.serials[new], self.config.bar_seconds, detected)
            if old:
                self.capture(old, old_rows)
            self.capture(new, new_rows)
            try:
                evidence = self.series.switch(old_symbol=old, new_symbol=new,
                    detected_ns=detected, old_rows=old_rows, new_rows=new_rows)
            except ValueError:
                raise Frozen('roll_reference_missing') from None
            self.j.record_mapping(evidence)
            self.record('mapping', dict(source_symbol=new, offset=self.series.offset))
            self.pending_mapping = None
            if old:
                if self.risk.quantity and not self.risk.sealed:
                    self.cancel(old)
                    raise Frozen('roll_initial_entry_incomplete')
                self.roll.request(old, new, side=self.risk.side if self.risk.quantity else 0,
                                  lots=self.risk.quantity, now_ns=now)
                self.roll_clock = time.monotonic_ns()
                self.record('roll', dict(phase=self.roll.state.phase))
        rows = completed_rows(self.serials[mapped], self.config.bar_seconds, now)
        self.capture(mapped, rows)
        signal = None
        for raw in rows:
            bar = self.series.append(symbol=mapped, row=raw, completed_at_ns=now)
            if bar is None:
                continue
            self.j.capture_signal(bar)
            if self.start_ns <= raw['datetime']:
                self.observed.add(bar['trading_day'])
            window = self.series.window()
            for side in (1, -1):
                self.pivots[side] = latest_confirmed_pivot(window, side=side,
                    left=self.config.risk.pivot_left, right=self.config.risk.pivot_right,
                    as_of_ns=now, previous=self.pivots[side], allow_nonpositive=True)
            if now < self.start_ns:
                continue
            signal = completed_cross_closed(window, self.config.fast_period,
                self.config.slow_period, completed_ns=now, allow_nonpositive=True)
        for discarded in self.series.take_discards():
            self.record('boundary', dict(reason=discarded['reason'], source_symbol=mapped,
                                        progress=discarded))
        if now >= self.start_ns and not self.prewarmed:
            before = [b for b in self.series.window() if b['end_ns'] < self.start_ns]
            if len(before) < self.series.maximum:
                raise Frozen('prewarm_insufficient')
            self.prewarmed = True
        reverse = (signal and signal.direction and self.risk.quantity
                   and signal.direction != self.risk.side)
        if self.roll.state.phase != 'idle':
            actions = self.roll.advance(positions=positions, pending_orders=self.api.get_order(),
                task_finished={symbol: self.task_done(symbol) for symbol in self.tasks},
                risk_exit=self.risk.exit_reason or ('ma_reverse' if reverse else None),
                stop_requested=stopping, mapping=mapped,
                now_ns=self.roll.state.started_ns+time.monotonic_ns()-self.roll_clock)
            for action in actions:
                if action['kind'] == 'cancel':
                    self.cancel(action['symbol'])
                elif action['kind'] == 'target':
                    self.target(action['symbol'], action['volume'], action['role'])
                elif action['kind'] == 'complete':
                    self.j.set('roll_count', self.j.get('roll_count', 0)+1)
                elif action['kind'] == 'freeze':
                    raise Frozen(action['reason'])
                self.record('roll', dict(phase=self.roll.state.phase))
            return
        if stopping:
            return
        if self.risk.quantity and (self.risk.exit_reason or reverse):
            symbol = next(s for s, pair in positions.items() if any(pair))
            if self.targets.get(symbol) != 0:
                self.target(symbol, 0, 'strategy_close')
            return
        if pending or not all(self.task_done(s) for s in self.tasks):
            if (self.intent_since and time.monotonic()-self.intent_since
                    > self.config.execution_timeout_seconds):
                raise Frozen('execution_timeout')
            return
        if now < self.start_ns or self.risk.quantity or signal is None or not signal.direction:
            return
        if signal.bar_start_ns <= self.last_signal:
            return
        self.last_signal = signal.bar_start_ns
        pivot = self.pivots[signal.direction]
        if pivot:
            pivot = replace(pivot, price=pivot.price+self.series.offset)
            if pivot.price <= 0:
                self.record('skipped', dict(reason='adjusted_stop_nonpositive'))
                return
        quote = self.quotes[mapped]
        price = getattr(quote, 'ask_price1' if signal.direction > 0 else 'bid_price1',
                        quote.last_price)
        if not math.isfinite(price):
            price = quote.last_price
        plan = plan_pivot_entry(self.config.risk, self.specs[mapped], side=signal.direction,
            reference_price=dec(price), pivot=pivot,
            available=dec(self.api.get_account().available),
            startup_equity=dec(self.config.initial_balance))
        self.record('signal', dict(signal=asdict(signal), entry_plan=asdict(plan), symbol=mapped))
        if not plan.lots:
            return
        self.entry_plan = plan
        self.j.set('entry_plan', public_values(asdict(plan)))
        self.risk = LogicalRisk(trade_id=uuid.uuid4().hex)
        self.target(mapped, signal.direction*plan.lots, 'strategy_open')


def execute_continuous(config, root, credentials, *, sdk, fee_multiplier=1,
                       stop_requested=lambda: False, progress=None, view_progress=None,
                       experiment_ref=None):
    j = ContinuousJournal.create(root, 'backtest', config,
                                 provenance() | {'experiment_ref': experiment_ref})
    j.set('experiment_ref', experiment_ref)
    j.set('fee_multiplier', fee_multiplier)
    needed = max(config.slow_period+2, config.risk.pivot_left+config.risk.pivot_right+2)
    engine_start = config.start-timedelta(
        days=max(30, needed*3 if config.bar_seconds == 86400 else 30))
    j.set('engine_start', str(engine_start))
    j.set('user_start', str(config.start))
    # 与锁定SDK的date参数完全相同，含前一交易日夜盘。
    start, end = _convert_user_input_to_nano(config.start, config.end)
    tracker = BacktestProgress(start, end)
    api, loop, quote = None, None, None
    status, reason, revision = 'failed', 'sdk_or_auth_or_permission_error', 0
    expected, last_publish = None, 0

    def publish(stage, *, success=False, terminal=False, force=False):
        nonlocal revision, last_publish
        current = loop.now if loop else None
        details = tracker.update(stage, current_ns=current, bars=j.get('signal_count', 0),
                                  fills=j.get('fill_count', 0), success=success)
        emit_progress(progress, 'research_progress', details=details)
        if loop:
            held = next((s for s, pair in positions_snapshot(api.get_position()).items()
                         if any(pair)), loop.series.symbol)
            risk = public_values(asdict(loop.risk))
            if held in loop.specs and loop.risk.quantity:
                risk['stop_price'] = public_values(logical_stop(loop.risk, spec=loop.specs[held]))
            emit_progress(progress, 'research_state', run_id=j.path.name, symbol=held,
                phase=loop.roll.state.phase, precision=config.precision, risk=risk,
                logical_risk=public_values(asdict(loop.risk)), roll=asdict(loop.roll.state),
                equity=api.get_account().balance, commission=api.get_account().commission)
        if view_progress and loop and quote and (force or time.monotonic()-last_publish >= .2):
            revision += 1
            frame = continuous_snapshot(j, config, quote, now=loop.now, revision=revision,
                                        progress=details, terminal=terminal)
            try:
                view_progress(frame)
            except Exception:
                pass
            last_publish = time.monotonic()

    try:
        publish('connecting')
        emit_progress(progress, 'connecting')
        account = sdk.TqSim(init_balance=float(config.initial_balance))
        backtest = sdk.TqBacktest(start_dt=engine_start, end_dt=config.end)
        api = tracked_api(sdk, j, account=account, auth=sdk.TqAuth(*credentials), backtest=backtest)
        try:
            calendar = api.get_trading_calendar(engine_start, config.end)
            days = pd.to_datetime(calendar['date']).dt.date
            if days.empty or days.min() > engine_start or days.max() < config.end:
                raise ValueError()
            expected = [str(d) for d, yes in zip(days, calendar['trading'], strict=True)
                        if bool(yes) and config.start <= d <= config.end]
        except Exception:
            raise Frozen('trading_calendar_unavailable') from None
        if not expected:
            raise Frozen('no_trading_days')
        j.set('calendar_expected_days', expected)
        main = api.get_quote(config.continuous)
        loop = ContinuousLoop(sdk, api, account, j, config,
                              multiplier=fee_multiplier, start_ns=start)
        loop.guard.start(positions_snapshot(api.get_position()), api.get_order(), activate=True)
        api.execution_guard = loop.guard
        j.set('initial_equity', str(config.initial_balance))
        last_clock, changed = None, time.monotonic()
        while True:
            now = int(backtest._current_dt)
            check_connections(api, set())
            if now != last_clock:
                last_clock, changed = now, time.monotonic()
            elif time.monotonic()-changed > config.timeout_seconds:
                raise Frozen('historical_time_stalled')
            loop.step(main, now, stopping=stop_requested())
            quote = loop.quotes.get(loop.series.symbol)
            acct = api.get_account()
            if math.isfinite(acct.balance) and math.isfinite(acct.commission):
                j.equity(now, float(acct.balance), float(acct.commission))
            publish('warmup' if now < start else 'backtesting')
            if stop_requested():
                status, reason = 'stopped', 'requested_stop'
                break
            api.wait_update(deadline=time.time()+1)
    except sdk.BacktestFinished:
        status, reason = 'backtest_finished', 'historical_replay_completed'
        if loop:
            loop.reconcile()
            from qf.research_runtime import capture_terminal_close
            if loop.series.symbol:
                terminal = capture_terminal_close(j,
                    SimpleNamespace(symbol=loop.series.symbol, bar_seconds=config.bar_seconds),
                    backtest, loop.serials[loop.series.symbol])
                if terminal:
                    loop.observed.add(trading_day(terminal))
            if loop.roll.state.phase != 'idle':
                status, reason = 'frozen', 'roll_incomplete_at_end'
            elif not loop.prewarmed or not j.get('signal_count'):
                status, reason = 'failed', 'historical_data_missing_or_incomplete'
        stats = getattr(account, 'tqsdk_stat', {})
        if not all(k in stats and math.isfinite(stats[k]) for k in ('end_balance', 'commission')):
            status, reason = 'failed', 'backtest_statistics_missing'
        else:
            j.set('sdk_statistics', {k: float(stats[k]) for k in ('end_balance', 'commission')})
            j.set('total_commission', str(stats['commission']))
        coverage = assess_coverage(expected_days=expected,
            observed_days=sorted(loop.observed) if loop else [], issues=[])
        j.set('coverage_check', coverage)
        if status == 'backtest_finished' and coverage['status'] != 'verified':
            status, reason = 'failed', 'historical_coverage_incomplete'
    except Frozen as exc:
        status, reason = 'frozen', str(exc)
    except Exception:
        status, reason = 'failed', 'sdk_or_auth_or_permission_error'
    finally:
        publish('saving')
        if api:
            try:
                if loop:
                    for symbol in loop.tasks:
                        loop.cancel(symbol)
                    loop.reconcile()
                    loop.guard.enabled = False
                j.set('final_positions', positions_snapshot(api.get_position()))
                if any(o.status != 'FINISHED' for o in api.get_order().values()):
                    status, reason = 'frozen', 'cancellation_unconfirmed'
            except Exception:
                if status == 'backtest_finished':
                    status, reason = 'frozen', 'final_reconciliation_incomplete'
            try:
                api.close()
            except Exception:
                status, reason = 'frozen', 'session_close_unconfirmed'
        context = loop.context if loop else dict(date=str(config.start),
            symbol=config.continuous, data_type='calendar')
        j.set('failure_context', context if status != 'backtest_finished' else {})
        j.set('status', status)
        j.set('reason', reason)
        try:
            j.export()
        except Exception:
            status, reason = 'failed', 'result_save_failed'
            j.set('status', status)
            j.set('reason', reason)
    try:
        summary = summarize_continuous_run(root, j.path.name)
    except ValueError:
        summary = dict(issue='结果记录不完整，不可可信复盘')
        if status == 'backtest_finished':
            status, reason = 'failed', 'result_integrity_failed'
    publish('completed' if status == 'backtest_finished' else status,
            success=status == 'backtest_finished', terminal=True, force=True)
    result = dict(run_id=j.path.name, status=status, reason=reason, summary=summary,
                  failure_context=j.get('failure_context'))
    j.close()
    return result
