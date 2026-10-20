"""单合约研究执行：SDK事件串行推进，目标、委托与成交分别核实。"""

import hashlib
import json
import math
import secrets
import time
import uuid
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
from tqsdk.datetime import _get_trading_day_from_timestamp, _get_trading_day_start_time

from qf.history import summarize_history
from qf.journal import PaperLock
from qf.ma_cross import completed_cross
from qf.pivot_stop import latest_confirmed_pivot, plan_pivot_entry
from qf.research_account import (
    account_schema,
    account_snapshot,
    account_totals,
    compact_account_snapshot,
    enable_account_evidence,
    save_account,
)
from qf.research_config import decimal_value as dec
from qf.research_config import public_values, validate_research_config
from qf.research_contract import contract_spec as contract_spec
from qf.research_contract import make_target_task
from qf.research_coverage import assess_coverage
from qf.research_journal import ResearchJournal, bar_end_ns, research_trade_key
from qf.research_progress import BacktestProgress
from qf.research_results import run_path, summarize_run
from qf.research_snapshot import view_snapshot
from qf.runtime import (
    check_connections,
    emit_progress,
    positions_snapshot,
    provenance,
    tracked_api,
    trades_snapshot,
    wait_ready,
)
from qf.safety import ExecutionScope, Frozen, Guard, settle_stop
from qf.trade_risk import (
    apply_entry_fill,
    close_trade_fills,
    empty_risk,
    protect,
    seal_entry,
    size_order,
)


def quote_ns(quote):
    stamp = pd.Timestamp(quote.datetime)
    if pd.isna(stamp):
        raise ValueError('报价时间缺失')
    return int((stamp.tz_localize('Asia/Shanghai') if stamp.tz is None else stamp).value)


def _rows(serial, seconds):
    summary = summarize_history(serial, seconds)
    if any(k not in ('empty',) for k in summary['issues']):
        raise Frozen('historical_data_invalid')
    return [dict(r, datetime=int(r['datetime'])) for r in serial.to_dict('records')
            if r['datetime'] > 0]


def capture_terminal_close(journal, config, backtest, serial):
    """锁定SDK的最终CLOSE发送证据；不在回放结束后补发策略信号。"""
    key = (config.symbol, config.bar_seconds*1_000_000_000)
    final = getattr(backtest, '_serials', {}).get(key)
    if (not isinstance(final, dict) or final.get('when') != 'CLOSE'
            or key in getattr(backtest, '_generators', {key: None})):
        return None
    rows = _rows(serial, config.bar_seconds)
    if not rows:
        return None
    row, item, close_ns = rows[-1], final.get('kline_or_tick'), final.get('timestamp')
    stamp, duration = row['datetime'], key[1]
    expected_close = (stamp+duration if config.bar_seconds < 86400 else
                      _get_trading_day_start_time(stamp+duration))-1000
    if (not isinstance(item, dict) or type(close_ns) is not int
            or close_ns != expected_close or not backtest._start_dt <= stamp <= backtest._end_dt
            or close_ns > backtest._end_dt or item.get('datetime') != stamp
            or any(item.get(k) != row[k] for k in
                   ('open', 'high', 'low', 'close', 'volume', 'close_oi'))):
        return None
    journal.capture_bars(config.symbol, config.bar_seconds, [row], sdk_closed_ns=close_ns)
    evidence = dict(time_ns=str(stamp), completed_at_ns=str(close_ns), signal_consumed=False,
                    source='SDK_3.10.2_terminal_CLOSE')
    journal.set('terminal_close_bar', evidence)
    return close_ns


def discover_contracts(sdk, credentials, *, continuous, start, end, timeout):
    import re
    match = re.fullmatch(r'KQ\.m@(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.([A-Za-z]+)', continuous)
    if not match:
        raise ValueError('品种无效')
    api = None
    try:
        api = tracked_api(sdk, None, account=sdk.TqSim(), auth=sdk.TqAuth(*credentials))
        symbols = api.query_quotes(ins_class='FUTURE', exchange_id=match[1],
                                   product_id=match[2], expired=None)
        quotes = [(s, api.get_quote(s)) for s in symbols
                  if re.fullmatch(re.escape(continuous[5:])+r'\d{3,4}', s)]
        wait_ready(api, lambda: all(math.isfinite(q.expire_datetime) for _, q in quotes),
                   timeout, set())
        first = pd.Timestamp(start, tz='Asia/Shanghai').timestamp()
        result = []
        for symbol, quote in quotes:
            if quote.expire_datetime >= first:
                item = dict(symbol=symbol, name=str(quote.instrument_name),
                            expire_datetime=quote.expire_datetime,
                            coverage='上市起点与账户历史权限需回测核实')
                for field, attr in [('price_tick', 'price_tick'),
                                    ('volume_multiple', 'volume_multiple'),
                                    ('margin_per_lot', 'margin'),
                                    ('commission_per_lot', 'commission')]:
                    value = getattr(quote, attr, float('nan'))
                    item[field] = value if math.isfinite(value) else None
                result.append(item)
        return sorted(result, key=lambda r: (r['expire_datetime'], r['symbol']))
    finally:
        if api:
            api.close()


class ResearchLoop:
    def __init__(self, sdk, api, account, journal, config, spec, *, paper, active, progress):
        self.sdk, self.api, self.account, self.journal = sdk, api, account, journal
        self.config, self.spec, self.paper, self.active = config, spec, paper, active
        self.progress = progress
        self.risk = journal.load_risk()
        self.phase = 'holding' if self.risk.quantity else 'flat'
        self.task = None
        self.quote = None
        self.target = self.risk.side*self.risk.quantity
        self.pending_since = None
        self.pending_direction = None
        self.pending_signal = self.pending_pivot = self.entry_plan = None
        self.pivots = {1: None, -1: None}
        self.block_before = journal.get('block_before', 0)
        self.last_bar = journal.get('last_bar', 0)
        self.seen = set()
        self.guard = Guard(journal, config.symbol,
                           scope=ExecutionScope(config.risk.max_lots or 1, True),
                           fill_handler=self.accept_fill)
        self.stopping_flat = False
        self.fee_day = None
        self.previous_day_fee = dec(0)
        self.last_equity_ns = 0
        self.as_of_ns = 0
        self.trimming_entry = False
        self.total_fee = dec(journal.get('total_commission', 0))
        self.startup_equity = dec(journal.get('initial_equity', config.initial_balance))
        self.account_evidence = account_schema(journal.db)
        self.latest_account = None

    def record(self, kind, now, payload=None, target=None):
        self.journal.commit_update(uuid.uuid4().hex, time_ns=now, kind=kind,
            payload=payload or {}, risk_state=self.risk, fills=[], target=target)

    def accept_fill(self, fill):
        if self.journal.has_fill(fill):
            return
        try:
            if fill['offset'] == 'OPEN':
                state = apply_entry_fill(self.risk, side=1 if fill['direction'] == 'BUY' else -1,
                    price=dec(fill['price']), quantity=fill['volume'], time_ns=fill['time_ns'],
                    risk=self.config.risk, spec=self.spec,
                    trade_id=self.risk.trade_id or uuid.uuid4().hex,
                    entry_plan=self.entry_plan)
            else:
                state = close_trade_fills(self.risk, [fill])
            role = 'strategy_open' if fill['offset'] == 'OPEN' else 'strategy_close'
            fee = dict(fill_key=research_trade_key(fill),
                       amount=str(self.spec.commission_per_lot*fill['volume']),
                       role=role)
            self.journal.commit_update('fill-'+research_trade_key(fill), time_ns=fill['time_ns'],
                kind='fill', payload={'phase': self.phase, **({'entry_plan':
                    public_values(asdict(self.entry_plan))} if self.entry_plan else {})},
                risk_state=state, fills=[fill],
                fill_fees=[fee] if self.account_evidence else None)
            self.risk = state
            self.as_of_ns = max(self.as_of_ns, fill['time_ns'])
            self.capture_account('fill')
        except ValueError:
            self.guard.freeze('fill_risk_mismatch')

    def new_task(self):
        self.task = make_target_task(self.sdk, self.api, self.config.symbol, self.quote)

    def submit(self, target, now):
        if not self.active:
            return
        payload = {'phase': self.phase}
        if target and self.entry_plan is not None:
            payload['entry_plan'] = public_values(asdict(self.entry_plan))
        self.record('intent', now, payload, target=target)
        if self.task is None:
            self.new_task()
        self.task.set_target_volume(target)
        self.target = target
        self.pending_since = time.monotonic()

    def begin_exit(self, now, reason, direction=None):
        if self.phase == 'exiting':
            if direction is not None:
                self.pending_direction = direction
            return
        self.phase, self.pending_direction = 'exiting', direction
        self.trimming_entry = False
        self.risk = replace(self.risk, exit_reason=reason)
        self.block_before = now
        self.journal.set('block_before', now)
        # 先落盘0目标；取消等待期间Guard也不再允许旧任务开仓。
        self.record('intent', now, {'reason': reason, 'phase': self.phase}, target=0)
        if self.task:
            self.task.cancel()
        self.target = 0
        self.pending_since = time.monotonic()

    def reconcile_task(self, now, orders):
        pending = any(o.status != 'FINISHED' for o in orders.values())
        if self.phase == 'exiting':
            if self.task and not self.risk.quantity and not pending:
                self.task.cancel()
            if self.task and self.task.is_finished() and not pending:
                self.task = None
            if self.task is None and not pending:
                if self.risk.quantity:
                    self.risk = seal_entry(self.risk)
                    self.submit(0, now)
                else:
                    self.risk = empty_risk()
                    self.phase = 'flat'
                    self.pending_since = None
                    self.record('reconciled', now, {'phase': 'flat'}, target=0)
        elif self.phase == 'entering' and not pending:
            remaining = abs(self.target) - self.risk.quantity
            if self.risk.quantity and 0 < remaining < self.spec.min_open_lots:
                if not self.trimming_entry:
                    self.trimming_entry = True
                    self.task.cancel()
                    self.pending_since = time.monotonic()
                    self.target = self.risk.side * self.risk.quantity
                    self.record('intent', now, {'phase': 'entering'}, target=self.target)
            if (remaining == 0 or self.trimming_entry) and (
                    not self.trimming_entry or self.task.is_finished()):
                if self.trimming_entry:
                    self.task = None
                    self.target = self.risk.side * self.risk.quantity
                self.risk, self.phase = seal_entry(self.risk), 'holding'
                self.pending_since, self.trimming_entry = None, False
                self.record('sealed', now, target=self.target)
        if self.pending_since and time.monotonic()-self.pending_since > \
                self.config.execution_timeout_seconds:
            self.guard.freeze('execution_timeout')

    def open_direction(self, direction, now, *, quote=None, pivot=None):
        if self.config.strategy_version == 2:
            reference = getattr(quote, 'ask_price1' if direction == 1 else 'bid_price1')
            if not math.isfinite(reference) or reference <= 0:
                self.record('skipped', now, {'reason': 'entry_quote_unavailable'})
                return
            decision = plan_pivot_entry(self.config.risk, self.spec, side=direction,
                reference_price=dec(reference), pivot=pivot,
                available=dec(self.api.get_account().available), startup_equity=self.startup_equity)
            self.entry_plan = decision
        else:
            decision = size_order(self.config.risk, self.spec,
                available=dec(self.api.get_account().available), startup_equity=self.startup_equity)
        self.record('skipped' if not decision.lots else 'signal', now,
                    {('entry_plan' if self.config.strategy_version == 2 else 'sizing'):
                        public_values(asdict(decision))})
        if decision.lots and self.active:
            self.guard.scope = ExecutionScope(decision.lots, True)
            self.risk = empty_risk()
            self.phase = 'entering'
            self.submit(direction*decision.lots, now)

    def equity(self, now):
        if now < self.last_equity_ns:
            return
        account = self.api.get_account()
        commission = dec(account.commission)
        day = _get_trading_day_from_timestamp(now)
        if self.fee_day is None:
            self.previous_day_fee = commission if self.paper else dec(0)
        elif day > self.fee_day:
            self.previous_day_fee = dec(0)
        self.total_fee += max(dec(0), commission-self.previous_day_fee)
        self.fee_day, self.previous_day_fee = day, commission
        self.last_equity_ns = now
        self.journal.equity(now, float(account.balance), float(self.total_fee),
                            total_commission=self.total_fee)

    def capture_account(self, trigger, *, status='active'):
        if not self.account_evidence or not self.as_of_ns:
            return
        detailed = trigger != 'bar_close' or self.latest_account is None
        snapshot = account_snapshot(self.api, time_ns=self.as_of_ns, status=status,
                                    totals=account_totals(self.journal.db),
                                    details=detailed)
        if trigger == 'bar_close' and not detailed:
            snapshot.update(
                positions=self.latest_account.get('positions', []),
                orders=self.latest_account.get('orders', []),
                trades=self.latest_account.get('trades', []),
                truncated=self.latest_account.get('truncated', {}),
                availability=self.latest_account.get('availability', {}))
        stored = compact_account_snapshot(snapshot) if trigger == 'bar_close' else snapshot
        save_account(self.journal, stored, trigger=trigger)
        self.latest_account = snapshot

    def step(self, quote, serial, *, minimum_bar, start_ns, end_ns, flatten):
        self.quote = quote
        check_connections(self.api, self.seen)
        for fill in trades_snapshot(self.api.get_trade()):
            self.guard.accept_fill(fill)
        positions, orders = positions_snapshot(self.api.get_position()), self.api.get_order()
        self.guard.check(positions, orders)
        now = quote_ns(quote)
        self.as_of_ns = max(self.as_of_ns, now, self.risk.last_fill_ns)
        if self.paper and (quote.expired or not math.isfinite(quote.expire_datetime)
                           or quote.expire_datetime <= time.time()+86400):
            self.guard.freeze('contract_near_expiry')
        if flatten:
            self.stopping_flat = True
            self.begin_exit(now, 'user_flatten')
        if self.risk.quantity and self.phase != 'exiting':
            updated = protect(self.risk, price=dec(quote.last_price), time_ns=now,
                               risk=self.config.risk, spec=self.spec)
            if updated != self.risk:
                self.risk = updated
                self.record('protection', now, {'price': str(quote.last_price)})
                self.capture_account('protection')
            if self.risk.exit_reason:
                self.begin_exit(now, self.risk.exit_reason)
        self.reconcile_task(now, orders)
        rows = _rows(serial, self.config.bar_seconds)
        if rows:
            self.journal.capture_bars(self.config.symbol, self.config.bar_seconds,
                                      [rows[-1]], completed=False)
        if len(rows) >= self.config.slow_period+2:
            completed = rows[-2]['datetime']
            finished_ns = min(bar_end_ns(completed, self.config.bar_seconds),
                              rows[-1]['datetime'])
            ready_ns = max(finished_ns, rows[-1]['datetime'])
            if completed > self.last_bar and now >= ready_ns:
                self.journal.capture_bars(self.config.symbol, self.config.bar_seconds, rows[:-1])
                self.capture_account('bar_close')
                self.last_bar = completed
                self.journal.set('last_bar', completed)
                if self.config.strategy_version == 2:
                    closed = [dict(r, end_ns=bar_end_ns(r['datetime'], self.config.bar_seconds))
                              for r in rows[:-1]]
                    for side in (1, -1):
                        self.pivots[side] = latest_confirmed_pivot(closed, side=side,
                            left=self.config.risk.pivot_left, right=self.config.risk.pivot_right,
                            as_of_ns=finished_ns, previous=self.pivots[side])
                signal = completed_cross(rows, self.config.fast_period, self.config.slow_period,
                                         completed_ns=ready_ns)
                if signal:
                    signal = replace(signal, completed_ns=finished_ns)
                if (signal and completed > minimum_bar and start_ns <= completed <= end_ns
                        and finished_ns > self.block_before and not self.stopping_flat):
                    self.record('signal', now, {'signal': public_values(asdict(signal))})
                    self.pending_signal = signal
                    self.pending_pivot = self.pivots[signal.direction]
                    if self.phase == 'flat':
                        direction = signal.direction
                        self.pending_direction = None
                        self.open_direction(direction, now, quote=quote, pivot=self.pending_pivot)
                    elif self.phase == 'exiting' and self.risk.exit_reason == 'ma_reverse':
                        self.pending_direction = signal.direction
                    elif signal.direction != self.risk.side:
                        self.begin_exit(now, 'ma_reverse', signal.direction)
        if self.phase == 'flat' and self.pending_direction is not None and not self.stopping_flat:
            direction, self.pending_direction = self.pending_direction, None
            self.open_direction(direction, now, quote=quote, pivot=self.pending_pivot)
        self.equity(now)
        emit_progress(self.progress, 'research_state', **public_values(dict(
            phase=self.phase, risk=asdict(self.risk), equity=str(self.api.get_account().balance),
            commission=str(self.total_fee), symbol=self.config.symbol,
            precision=self.config.precision, run_id=self.journal.path.name,
            account=self.latest_account)))
        return self.stopping_flat and self.phase == 'flat'


def execute_research(mode, config, root, credentials, *, sdk=None, activate=False, resume=None,
                     fee_multiplier=1, stop_requested=lambda: False,
                     flatten_requested=lambda: False, progress=None, experiment_ref=None,
                     view_progress=None, view_requested=None, job_binding=None):
    config = validate_research_config(config.public())
    if config.schema_version == 3 and mode != 'backtest':
        raise ValueError('主力连续版本只用于历史回测，模拟请使用固定合约实验')
    if (mode not in ('backtest', 'paper') or type(activate) is not bool
            or (mode != 'paper' and (activate or resume))
            or type(fee_multiplier) is not int or fee_multiplier not in (1, 2)
            or (mode == 'paper' and fee_multiplier != 1)):
        raise ValueError('研究运行模式无效')
    if sdk is None:
        import tqsdk as sdk
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if config.schema_version == 3:
        from qf.continuous_runtime import execute_continuous
        return execute_continuous(config, root, credentials, sdk=sdk,
            fee_multiplier=fee_multiplier, stop_requested=stop_requested, progress=progress,
            view_progress=view_progress, experiment_ref=experiment_ref,
            view_requested=view_requested, job_binding=job_binding)
    with PaperLock(root) if mode == 'paper' else nullcontext():
        return _run(sdk, mode, config, root, credentials, activate, resume, fee_multiplier,
                    stop_requested, flatten_requested, progress, experiment_ref, view_progress,
                    view_requested, job_binding)


def _run(sdk, mode, config, root, credentials, activate, resume, multiplier,
         stop_requested, flatten_requested, progress, experiment_ref, view_progress,
         view_requested=None, job_binding=None):
    j = (ResearchJournal.resume(run_path(root, resume), config.public()) if resume else
         ResearchJournal.create(root, mode, config.public(),
                                provenance() | {'experiment_ref': experiment_ref}))
    if mode == 'backtest':
        enable_account_evidence(j)
    if job_binding is not None:
        j.set('job_binding', job_binding)
    if not resume:
        j.set('experiment_ref', experiment_ref)
    api, loop, account = None, None, None
    paper, status, reason = mode == 'paper', 'failed', 'sdk_or_auth_or_permission_error'
    confirmed = True
    tracker, quote, expected_days = None, None, None
    revision, last_publish = 0, 0

    def publish(stage, *, current=None, terminal=False, success=False, force=False):
        nonlocal revision, last_publish
        if tracker is None:
            return
        bars = j.db.execute('SELECT count(*) FROM research_bars').fetchone()[0]
        last = j.db.execute('SELECT data FROM research_bars ORDER BY time_ns DESC LIMIT 1')
        last = last.fetchone()
        if last and not json.loads(last[0])['completed']:
            bars -= 1
        fills = j.db.execute('SELECT count(*) FROM fills').fetchone()[0]
        state = tracker.update(stage, current_ns=current, bars=bars, fills=fills, success=success)
        if paper:
            state['percent'] = None
        emit_progress(progress, 'research_progress', details=state)
        if (view_progress is not None and quote is not None and loop is not None
                and (view_requested is None or view_requested())
                and (force or time.monotonic()-last_publish >= .2)):
            revision += 1
            frame = view_snapshot(j, config, quote, now=max(loop.as_of_ns, tracker.current or 0),
                                  revision=revision, progress=state, terminal=terminal)
            try:
                view_progress(frame)
            except Exception:
                # 展示窗口关闭或回调失败不影响交易和结果留存。
                pass
            last_publish = time.monotonic()

    try:
        if resume:
            metadata = json.loads((j.path/'metadata.json').read_text('utf-8'))
            if (metadata.get('source_sha256') != provenance()['source_sha256']
                    or j.get('risk_state') is None or j.expected_position()
                    or j.get('pending_intent', False)):
                raise Frozen('resume_incomplete')
        salt = j.get('identity_salt', secrets.token_hex(32))
        binding = hashlib.sha256((salt+credentials[0]).encode()).hexdigest()
        if resume and j.get('account_binding') != binding:
            raise Frozen('resume_account_mismatch')
        j.set('identity_salt', salt)
        j.set('account_binding', binding)
        account = sdk.TqKq() if paper else sdk.TqSim(init_balance=float(config.initial_balance))
        options = dict(account=account, auth=sdk.TqAuth(*credentials))
        start_ns, end_ns = 0, 2**63-1
        if not paper:
            backtest = sdk.TqBacktest(start_dt=config.start, end_dt=config.end)
            options['backtest'] = backtest
            start_ns, end_ns = backtest._start_dt, backtest._end_dt
        tracker = BacktestProgress(start_ns, end_ns)
        publish('connecting')
        emit_progress(progress, 'connecting')
        api = tracked_api(sdk, j, **options)
        publish('history')
        if not paper and config.strategy_version == 2:
            try:
                calendar = api.get_trading_calendar(config.start, config.end)
                dates = pd.to_datetime(calendar['date']).dt.date
                if dates.empty or dates.min() > config.start or dates.max() < config.end:
                    raise ValueError('calendar coverage')
                expected_days = sorted(str(d) for d, trading in zip(dates, calendar['trading'],
                    strict=True) if bool(trading) and config.start <= d <= config.end)
            except Exception:
                raise Frozen('trading_calendar_unavailable') from None
            if not expected_days:
                raise Frozen('no_trading_days')
        quote = api.get_quote(config.symbol)
        main = api.get_quote(config.continuous) if paper else None
        if config.precision == 'tick':
            ticks = api.get_tick_serial(config.symbol, data_length=2)
            wait_ready(api, lambda: int(ticks.iloc[-1].datetime) > 0,
                        config.timeout_seconds, set())
        else:
            api.get_kline_serial(config.symbol, 60, data_length=2)
        serial = api.get_kline_serial(config.symbol, config.bar_seconds,
                                      data_length=max(200, config.slow_period+2))
        publish('warmup')
        wait_ready(api, lambda: (math.isfinite(quote.last_price) and bool(quote.datetime)
            and len(_rows(serial, config.bar_seconds)) >= config.slow_period+2
            and math.isfinite(api.get_account().balance)), config.timeout_seconds, set())
        if paper and main.underlying_symbol != config.symbol:
            raise Frozen('underlying_changed')
        if (not paper and config.strategy_version == 2
                and math.isfinite(quote.expire_datetime)
                and config.end > pd.Timestamp(quote.expire_datetime, unit='s', tz='UTC')
                .tz_convert('Asia/Shanghai').date()):
            raise Frozen('contract_range_exceeds_expiry')
        spec = contract_spec(api, account, config.symbol, quote, paper=paper, multiplier=multiplier)
        if not resume:
            j.set('initial_equity', api.get_account().balance)
            j.commit_update('initial', time_ns=quote_ns(quote), kind='reconciled', payload={},
                            risk_state=empty_risk(), fills=[])
        j.set('fee_multiplier', multiplier)
        j.set('cost_source', spec.cost_source)
        j.set('contract_spec', public_values(asdict(spec)))
        loop = ResearchLoop(sdk, api, account, j, config, spec, paper=paper,
                             active=activate or not paper, progress=progress)
        if not resume:
            loop.guard.baseline = {f['key'] for f in trades_snapshot(api.get_trade())}
            j.set('baseline_trades', sorted(loop.guard.baseline))
        else:
            for fill in trades_snapshot(api.get_trade()):
                loop.guard.accept_fill(fill)
        loop.guard.start(positions_snapshot(api.get_position()), api.get_order(),
                         activate=loop.active, resume=bool(resume))
        api.execution_guard = loop.guard
        minimum = int(serial.iloc[-2].datetime) if paper else 0
        j.set('status', 'active' if loop.active else 'observing')
        while True:
            if paper and main.underlying_symbol != config.symbol:
                loop.guard.freeze('underlying_changed')
            flat = loop.step(quote, serial, minimum_bar=minimum, start_ns=start_ns,
                             end_ns=end_ns, flatten=flatten_requested())
            current = quote_ns(quote) if paper else getattr(backtest, '_current_dt', None)
            publish('simulating' if paper else 'backtesting', current=current)
            if (not paper and tracker.snapshot()['last_advance_age_seconds']
                    > config.timeout_seconds):
                raise Frozen('historical_time_stalled')
            if stop_requested() or flat:
                status, reason = 'stopped', 'flatten_confirmed' if flat else 'requested_stop'
                break
            api.wait_update(deadline=time.time()+1)
    except sdk.BacktestFinished:
        status, reason = ('backtest_finished', 'historical_replay_completed') if not paper else (
            'failed', 'unexpected_replay_end')
        stats = getattr(account, 'tqsdk_stat', {})
        if not paper and loop is not None and config.strategy_version == 2:
            try:
                closed = capture_terminal_close(j, config, backtest, serial)
                if closed is not None:
                    loop.as_of_ns = max(loop.as_of_ns, closed)
            except (Frozen, ValueError, TypeError, KeyError):
                status, reason = 'failed', 'terminal_bar_evidence_invalid'
        has_data = loop is not None and j.db.execute(
            'SELECT count(*) FROM research_bars').fetchone()[0] > 0
        if not has_data:
            status, reason = 'failed', 'historical_data_missing_or_incomplete'
        elif not paper and not all(k in stats and math.isfinite(stats[k])
                                   for k in ('end_balance', 'commission')):
            status, reason = 'failed', 'backtest_statistics_missing'
        elif not paper and stats:
            j.set('sdk_statistics', {k: float(stats[k]) for k in ('end_balance', 'commission')
                                     if k in stats and math.isfinite(stats[k])})
            if 'commission' in stats:
                j.set('total_commission', str(stats['commission']))
    except Frozen as exc:
        status, reason = 'frozen', str(exc)
    except Exception:
        status, reason = 'failed', 'sdk_or_auth_or_permission_error'
    finally:
        publish('saving')
        if loop:
            loop.guard.enabled = False
        if api:
            try:
                j.set('final_positions', positions_snapshot(api.get_position()))
            except Exception:
                j.set('positions_unconfirmed', True)
            try:
                if loop:
                    if not paper:
                        if loop.task:
                            loop.task.cancel()
                        confirmed = not any(o.status != 'FINISHED'
                                            for o in api.get_order().values())
                    else:
                        confirmed = settle_stop(api, loop.task, api.get_order(), j.owned(),
                                                 config.execution_timeout_seconds)
                    for fill in trades_snapshot(api.get_trade()):
                        loop.guard.accept_fill(fill)
                    loop.guard.check(positions_snapshot(api.get_position()), api.get_order())
                    j.set('final_positions', positions_snapshot(api.get_position()))
                    if not paper:
                        loop.capture_account('terminal', status='last_snapshot')
            except Exception:
                confirmed = False
            try:
                api.close()
            except Exception:
                confirmed = False
            if not confirmed and status != 'frozen':
                status, reason = 'frozen', 'cancellation_unconfirmed'
        if status == 'backtest_finished' and config.strategy_version == 2:
            observed = set()
            for stamp, raw in j.db.execute('SELECT time_ns,data FROM research_bars'):
                if json.loads(raw).get('completed') and start_ns <= stamp <= end_ns:
                    day = str(pd.Timestamp(_get_trading_day_from_timestamp(stamp), tz='UTC')
                              .tz_convert('Asia/Shanghai').date())
                    observed.add(day)
            coverage = assess_coverage(expected_days=expected_days,
                                       observed_days=sorted(observed), issues=[])
            j.set('coverage_check', coverage)
            if coverage['status'] != 'verified':
                status, reason = 'failed', 'historical_coverage_incomplete'
        j.set('status', status)
        j.set('reason', reason)
        j.set('cancellation_confirmed', confirmed)
        try:
            j.export()
        except Exception:
            status, reason = 'failed', 'result_save_failed'
            j.set('status', status)
            j.set('reason', reason)
    try:
        summary = summarize_run(root, j.path.name)
    except ValueError:
        summary = {'issue': '结果记录不完整，不可可信复盘'}
        if status == 'backtest_finished':
            status, reason = 'failed', 'result_integrity_failed'
    publish('completed' if status == 'backtest_finished' else status, terminal=True,
            success=status == 'backtest_finished', force=True)
    j.close()
    return dict(run_id=j.path.name, status=status, reason=reason, summary=summary)
