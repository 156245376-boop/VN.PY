"""本机内存回测：一次载入数据，顺序推进交易状态，不做逐柱I/O。"""

import hashlib
import json
import time
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal

import pandas as pd

from qf.continuous_risk import (
    LogicalRisk,
    apply_logical_fill,
    logical_gross,
    logical_stop,
    protect_logical,
    seal_logical,
)
from qf.local_signals import ma_cross_signals
from qf.pivot_stop import Pivot, plan_pivot_entry
from qf.research_config import decimal_value, public_values

ZERO = Decimal(0)


@dataclass(frozen=True)
class LocalRunResult:
    dataset_id: str
    config: dict
    status: str
    reason: str
    signals: list[dict]
    fills: list[dict]
    trades: list[dict]
    equity: list[dict]
    rolls: list[dict]
    entry_rejections: list[dict]
    fees: Decimal
    gross_pnl: Decimal
    final_equity: Decimal
    closed_trade_count: int
    open_position: int
    engine_kind: str
    engine_version: str
    compute_backend: str
    precision: str
    fee_multiplier: int
    profile: dict

    def public(self):
        return public_values({
            'dataset_id': self.dataset_id,
            'config': self.config,
            'status': self.status,
            'reason': self.reason,
            'signals': self.signals,
            'fills': self.fills,
            'trades': self.trades,
            'equity': self.equity,
            'rolls': self.rolls,
            'entry_rejections': self.entry_rejections,
            'fees': self.fees,
            'gross_pnl': self.gross_pnl,
            'final_equity': self.final_equity,
            'closed_trade_count': self.closed_trade_count,
            'open_position': self.open_position,
            'engine_kind': self.engine_kind,
            'engine_version': self.engine_version,
            'compute_backend': self.compute_backend,
            'precision': self.precision,
            'fee_multiplier': self.fee_multiplier,
        })

    def fingerprint(self):
        payload = self.public()
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest()


class LocalBacktestEngine:
    def __init__(self, *, fill_fraction=Decimal(1), fee_multiplier=1):
        fill_fraction = decimal_value(fill_fraction)
        if not ZERO < fill_fraction <= Decimal(1):
            raise ValueError('成交比例必须在0到1之间')
        if fee_multiplier not in (1, 2):
            raise ValueError('费用倍数必须为1或2')
        self.fill_fraction = fill_fraction
        self.fee_multiplier = fee_multiplier

    def run(self, dataset, config, progress=None, cancel=None):
        started = time.perf_counter()
        cancel = cancel or (lambda: False)
        progress = progress or (lambda *_args, **_kwargs: None)
        try:
            self._validate(dataset, config)
            runner = _LocalRunner(
                self, dataset, config, progress, cancel, started
            )
            try:
                return runner.execute()
            except _LocalFailure as exc:
                return runner._result('failed', exc.code)
        except _LocalFailure as exc:
            return self._failed_result(
                dataset, config, exc.code, started, self.fee_multiplier
            )
        except (ArithmeticError, KeyError, TypeError, ValueError):
            return self._failed_result(
                dataset,
                config,
                'local_engine_input_invalid',
                started,
                self.fee_multiplier,
            )

    @staticmethod
    def _validate(dataset, config):
        if not getattr(dataset, 'coverage_complete', False):
            raise _LocalFailure('coverage_incomplete')
        if getattr(dataset, 'precision', '') == 'tick' or config.precision == 'tick':
            raise _LocalFailure('tick_path_not_available')
        if (
            getattr(dataset, 'bar_seconds', None) != config.bar_seconds
            or 'duration' in dataset.frame
            and set(dataset.frame['duration'].astype(int)) != {config.bar_seconds}
        ):
            raise _LocalFailure('bar_period_mismatch')
        if (
            getattr(dataset, 'continuous', '')
            and dataset.continuous != config.continuous
        ):
            raise _LocalFailure('dataset_continuous_mismatch')
        required = {
            'symbol',
            'duration',
            'time_ns',
            'open',
            'high',
            'low',
            'close',
            'actual_open',
            'actual_high',
            'actual_low',
            'actual_close',
            'offset',
            'completed',
            'completed_ns',
        }
        if dataset.frame.empty or not required <= set(dataset.frame.columns):
            raise _LocalFailure('dataset_incomplete')
        missing = sorted(
            set(dataset.frame['symbol'].astype(str))-set(dataset.specs)
        )
        if missing:
            raise _LocalFailure('contract_spec_missing')

    @staticmethod
    def _failed_result(dataset, config, reason, started, fee_multiplier):
        return LocalRunResult(
            dataset_id=str(getattr(dataset, 'dataset_id', '')),
            config=config.public(),
            status='failed',
            reason=reason,
            signals=[],
            fills=[],
            trades=[],
            equity=[],
            rolls=[],
            entry_rejections=[],
            fees=ZERO,
            gross_pnl=ZERO,
            final_equity=Decimal(str(config.initial_balance)),
            closed_trade_count=0,
            open_position=0,
            engine_kind='local_research',
            engine_version='local_research_v1',
            compute_backend='cpu',
            precision=config.precision,
            fee_multiplier=fee_multiplier,
            profile={
                'elapsed_seconds': time.perf_counter()-started,
                'bars_processed': 0,
                'intrabar_stop_first': False,
            },
        )


class _LocalFailure(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _LocalRunner:
    def __init__(self, engine, dataset, config, progress, cancel, started):
        self.engine = engine
        self.dataset = dataset
        self.config = config
        self.progress = progress
        self.cancel = cancel
        self.started = started
        self.frame = dataset.frame.reset_index(drop=True)
        self.initial = Decimal(str(config.initial_balance))
        self.risk = None
        self.current_symbol = None
        self.last_mark = ZERO
        self.active = None
        self.pending = None
        self.fills = []
        self.trades = []
        self.equity = []
        self.rolls = []
        self.entry_rejections = []
        self.fees = ZERO
        self.closed_gross = ZERO
        self.sequence = 0
        self.intrabar_stop = False
        self.public_signals = []
        self.pivots = {1: [], -1: []}
        self.pivot_confirmations = {1: [], -1: []}

    def execute(self):
        signals = ma_cross_signals(
            self.frame,
            fast=self.config.fast_period,
            slow=self.config.slow_period,
            bar_seconds=self.config.bar_seconds,
        )
        signals = [self._signal(item) for item in signals]
        signals = [
            item
            for item in signals
            if self.config.start
            <= self._date(int(item['time_ns']))
            <= self.config.end
        ]
        self.public_signals = signals
        signal_by_bar = {}
        for item in signals:
            if item['bar_index'] in signal_by_bar:
                raise _LocalFailure('duplicate_signal_bar')
            if item['bar_index'] >= len(self.frame):
                raise _LocalFailure('signal_bar_mismatch')
            if item['time_ns'] != str(self.frame.iloc[item['bar_index']]['time_ns']):
                raise _LocalFailure('signal_bar_mismatch')
            signal_by_bar[item['bar_index']] = item

        eligible = []
        for index, row in enumerate(self.frame.itertuples(index=False)):
            day = self._date(int(row.time_ns))
            if self.config.start <= day <= self.config.end:
                eligible.append(index)
        if not eligible:
            raise _LocalFailure('requested_range_empty')
        eligible_set = set(eligible)
        self.pivots = self._build_pivots()

        for index, row in enumerate(self.frame.itertuples(index=False)):
            if index not in eligible_set:
                continue
            if self.cancel():
                return self._result('stopped', 'requested_stop')
            if not bool(row.completed):
                continue
            self._prepare_row(row, index)

            symbol = str(row.symbol)
            if self.risk is not None and self.current_symbol != symbol:
                reverse = (
                    self.pending is not None
                    and self.pending['direction'] != self.risk.side
                )
                if reverse:
                    self._close_position(
                        self.last_mark,
                        int(row.time_ns),
                        index,
                        'ma_reverse',
                        price_source='prior_contract_close_estimate',
                    )
                else:
                    self._roll_position(row, index)

            if self.pending is not None:
                signal = self.pending
                self.pending = None
                if self.risk is not None:
                    if signal['direction'] != self.risk.side:
                        self._close_position(
                            self._decimal(row.actual_open),
                            int(row.time_ns),
                            index,
                            'ma_reverse',
                        )
                        self._open_position(signal, row, index)
                else:
                    self._open_position(signal, row, index)

            self._protect_bar(row, index)
            if index in signal_by_bar:
                self.pending = signal_by_bar[index]

            self._append_equity(row, index)
            self.progress(
                'backtesting',
                completed_bars=len(self.equity),
                fill_count=len(self.fills),
                current_ns=str(int(row.time_ns)),
                percent=int((index+1)*100/max(1, len(self.frame))),
            )
        return self._result('backtest_finished', 'historical_replay_completed')

    def _prepare_row(self, row, index):
        if int(row.duration) != self.config.bar_seconds:
            raise _LocalFailure('bar_period_mismatch')
        symbol = str(row.symbol)
        spec = self.dataset.specs.get(symbol)
        if spec is None:
            raise _LocalFailure('contract_spec_missing')
        actual = {
            name: self._decimal(getattr(row, 'actual_'+name))
            for name in ('open', 'high', 'low', 'close')
        }
        if (
            min(actual.values()) <= 0
            or actual['high']
            < max(actual['open'], actual['low'], actual['close'])
            or actual['low']
            > min(actual['open'], actual['high'], actual['close'])
        ):
            raise _LocalFailure('invalid_bar')
        if int(row.time_ns) <= 0:
            raise _LocalFailure('invalid_bar_time')
        if self.fills and int(row.time_ns) < int(self.fills[-1]['time_ns']):
            raise _LocalFailure('time_order')
        if index > 0:
            previous = int(self.frame.iloc[index-1]['time_ns'])
            if int(row.time_ns) <= previous:
                raise _LocalFailure('time_order')

    @staticmethod
    def _signal(raw):
        if not isinstance(raw, dict):
            raise _LocalFailure('signal_invalid')
        bar_index = raw.get('bar_index')
        direction = raw.get('direction')
        stamp = raw.get('time_ns')
        completed = raw.get('completed_ns')
        if (
            type(bar_index) is not int
            or bar_index < 0
            or direction not in (-1, 1)
            or not isinstance(stamp, str)
            or not isinstance(completed, str)
        ):
            raise _LocalFailure('signal_invalid')
        try:
            int(stamp)
            int(completed)
        except ValueError:
            raise _LocalFailure('signal_invalid') from None
        return dict(raw)

    def _open_position(self, signal, row, bar_index):
        spec = self.dataset.specs[str(row.symbol)]
        pivot = self._pivot_at(signal['direction'], int(signal['completed_ns']))
        actual_pivot = None
        offset = self._decimal(row.offset)
        if pivot is not None:
            actual_pivot = Pivot(
                pivot.kind,
                pivot.price+offset,
                pivot.bar_start_ns,
                pivot.confirmed_ns,
                pivot.left,
                pivot.right,
            )
        plan = plan_pivot_entry(
            self.config.risk,
            spec,
            side=signal['direction'],
            reference_price=self._decimal(row.actual_open),
            pivot=actual_pivot,
            available=self._available(),
            startup_equity=self.initial,
        )
        if plan.lots < 1 or plan.stop_price is None:
            self.entry_rejections.append({
                'time_ns': str(int(row.time_ns)),
                'signal_bar': signal['bar_index'],
                'symbol': str(row.symbol),
                'direction': signal['direction'],
                'reason': plan.reason,
            })
            return
        quantity = self._filled_quantity(plan.lots, spec.lot_step)
        if quantity < spec.min_open_lots:
            self.entry_rejections.append({
                'time_ns': str(int(row.time_ns)),
                'signal_bar': signal['bar_index'],
                'symbol': str(row.symbol),
                'direction': signal['direction'],
                'reason': 'partial_below_minimum',
            })
            return
        trade_id = (
            f'trade-{int(row.time_ns)}-{signal["bar_index"]}-{self.sequence}'
        )
        entry_price = self._decimal(row.actual_open)
        fill = self._fill(
            symbol=str(row.symbol),
            direction='BUY' if signal['direction'] == 1 else 'SELL',
            offset='OPEN',
            role='strategy_open',
            volume=quantity,
            requested_volume=plan.lots,
            price=entry_price,
            time_ns=int(row.time_ns),
            execution_bar=bar_index,
            signal_bar=signal['bar_index'],
            trade_id=trade_id,
            fee=self._commission(spec, quantity),
        )
        state = LogicalRisk(trade_id=trade_id)
        state = apply_logical_fill(
            state,
            fill,
            role='strategy_open',
            spec=spec,
            entry_plan=plan,
            risk=self.config.risk,
        )
        state = seal_logical(state)
        if state.exit_reason:
            raise _LocalFailure(state.exit_reason)
        self.risk = state
        self.current_symbol = str(row.symbol)
        self.last_mark = entry_price
        self.active = {
            'trade_id': trade_id,
            'side': signal['direction'],
            'quantity': quantity,
            'requested_quantity': plan.lots,
            'first_symbol': str(row.symbol),
            'last_symbol': str(row.symbol),
            'entry_time_ns': int(row.time_ns),
            'entry_price': state.entry_price,
            'initial_stop': plan.stop_price,
            'entry_plan': {
                'side': plan.side,
                'lots': plan.lots,
                'reference_price': str(plan.reference_price),
                'stop_price': str(plan.stop_price),
                'distance_ticks': str(plan.distance_ticks),
                'planned_r': str(plan.planned_r),
                'reason': plan.reason,
            },
            'fees': ZERO,
            'fill_count': 0,
        }
        self._record_fill(fill)

    def _build_pivots(self):
        rows = [
            item
            for item in self.frame.itertuples(index=False)
            if bool(item.completed)
        ]
        left = self.config.risk.pivot_left
        right = self.config.risk.pivot_right
        result = {1: [], -1: []}
        for index in range(left, len(rows)-right):
            source = rows[index]
            neighbors = rows[index-left:index]+rows[index+1:index+right+1]
            confirmed_ns = int(rows[index+right].completed_ns)
            for side, kind, key, comparison in (
                (1, 'low', 'low', lambda value, other: value < other),
                (-1, 'high', 'high', lambda value, other: value > other),
            ):
                value = self._decimal(getattr(source, key))
                if all(
                    comparison(value, self._decimal(getattr(item, key)))
                    for item in neighbors
                ):
                    result[side].append({
                        'confirmed_ns': confirmed_ns,
                        'pivot': Pivot(
                            kind,
                            value,
                            int(source.time_ns),
                            confirmed_ns,
                            left,
                            right,
                        ),
                    })
        for events in result.values():
            events.sort(
                key=lambda item: (
                    item['confirmed_ns'],
                    item['pivot'].bar_start_ns,
                )
            )
        self.pivot_confirmations = {
            side: [item['confirmed_ns'] for item in events]
            for side, events in result.items()
        }
        return result

    def _pivot_at(self, side, as_of_ns):
        events = self.pivots[side]
        position = bisect_right(self.pivot_confirmations[side], as_of_ns)-1
        return events[position]['pivot'] if position >= 0 else None

    def _close_position(
        self,
        price,
        time_ns,
        bar_index,
        reason,
        *,
        role='strategy_close',
        intrabar_resolution=None,
        price_source='bar_price',
    ):
        spec = self.dataset.specs[self.current_symbol]
        quantity = self.risk.quantity
        stop_before = logical_stop(self.risk, spec=spec)
        fill = self._fill(
            symbol=self.current_symbol,
            direction='SELL' if self.risk.side == 1 else 'BUY',
            offset='CLOSE',
            role=role,
            volume=quantity,
            requested_volume=quantity,
            price=self._decimal(price),
            time_ns=time_ns,
            execution_bar=bar_index,
            signal_bar=None,
            trade_id=self.risk.trade_id,
            fee=self._commission(spec, quantity),
            intrabar_resolution=intrabar_resolution,
            price_source=price_source,
        )
        self.risk = apply_logical_fill(
            self.risk,
            fill,
            role=role,
            spec=spec,
            entry_plan=None,
            risk=self.config.risk,
        )
        self._record_fill(fill)
        if role == 'strategy_close':
            self.risk = replace(self.risk, exit_reason=reason)
            self._finalize_trade(
                exit_time_ns=time_ns,
                exit_price=self._decimal(price),
                reason=reason,
                final_stop=stop_before,
            )

    def _roll_position(self, row, bar_index):
        if self.risk is None or self.current_symbol == str(row.symbol):
            return
        old_symbol = self.current_symbol
        new_symbol = str(row.symbol)
        old_spec = self.dataset.specs[old_symbol]
        new_spec = self.dataset.specs[new_symbol]
        quantity = self.risk.quantity
        if (
            new_spec.volume_multiple != old_spec.volume_multiple
            or quantity < new_spec.min_open_lots
            or quantity % new_spec.lot_step
        ):
            raise _LocalFailure('roll_spec_incompatible')
        closed_segment = (
            logical_gross(
                self.risk,
                price=self.last_mark,
                spec=old_spec,
            )
            - self.risk.realized_gross
        )
        available = self._available()+closed_segment
        if available < new_spec.margin_per_lot*quantity:
            raise _LocalFailure('roll_unaffordable')
        old_stop = logical_stop(self.risk, spec=old_spec)
        self._close_position(
            self.last_mark,
            int(row.time_ns),
            bar_index,
            'roll_transfer',
            role='roll_out',
            price_source='prior_contract_close_estimate',
        )
        if self.risk.exit_reason:
            self._finalize_trade(
                exit_time_ns=int(row.time_ns),
                exit_price=self.last_mark,
                reason=self.risk.exit_reason,
                final_stop=old_stop,
            )
            return
        fill = self._fill(
            symbol=new_symbol,
            direction='BUY' if self.risk.side == 1 else 'SELL',
            offset='OPEN',
            role='roll_in',
            volume=quantity,
            requested_volume=quantity,
            price=self._decimal(row.actual_open),
            time_ns=int(row.time_ns),
            execution_bar=bar_index,
            signal_bar=None,
            trade_id=self.risk.trade_id,
            fee=self._commission(new_spec, quantity),
            price_source='new_contract_open',
        )
        self.risk = apply_logical_fill(
            self.risk,
            fill,
            role='roll_in',
            spec=new_spec,
            entry_plan=None,
            risk=self.config.risk,
        )
        self.current_symbol = new_symbol
        self.last_mark = self._decimal(row.actual_open)
        self._record_fill(fill)
        new_stop = logical_stop(self.risk, spec=new_spec)
        self.active['last_symbol'] = new_symbol
        self.rolls.append({
            'time_ns': str(int(row.time_ns)),
            'old_symbol': old_symbol,
            'new_symbol': new_symbol,
            'quantity': quantity,
            'old_stop': str(old_stop),
            'new_stop': str(new_stop),
            'initial_r': str(self.risk.initial_r),
            'floor_gross': str(self.risk.floor_gross),
            'stage': self.risk.stage,
            'resolution': 'same_time_close_then_reopen',
        })

    def _protect_bar(self, row, bar_index):
        if self.risk is None or not self.risk.quantity:
            return
        spec = self.dataset.specs[self.current_symbol]
        open_ = self._decimal(row.actual_open)
        high = self._decimal(row.actual_high)
        low = self._decimal(row.actual_low)
        close = self._decimal(row.actual_close)
        target = self._target_price(self.risk, spec)
        stop_before = logical_stop(self.risk, spec=spec)
        if stop_before is None:
            raise _LocalFailure('risk_stop_missing')
        now = int(row.time_ns)
        long = self.risk.side == 1
        gap_stop = open_ <= stop_before if long else open_ >= stop_before
        gap_target = open_ >= target if long else open_ <= target
        stop_hit = low <= stop_before if long else high >= stop_before
        target_hit = high >= target if long else low <= target
        if gap_stop:
            self._close_position(
                open_, now, bar_index, self._stop_reason(self.risk)
            )
            return
        if gap_target:
            self._close_position(
                open_,
                now,
                bar_index,
                'take_profit',
                intrabar_resolution='gap_target',
            )
            return
        if stop_hit and target_hit:
            self.intrabar_stop = True
            self._close_position(
                stop_before,
                now,
                bar_index,
                self._stop_reason(self.risk),
                intrabar_resolution='conservative_stop_first',
            )
            return
        if stop_hit:
            self._close_position(
                stop_before, now, bar_index, self._stop_reason(self.risk)
            )
            return

        favorable = high if long else low
        before_stage = self.risk.stage
        self.risk = protect_logical(
            self.risk,
            price=favorable,
            time_ns=now,
            risk=self.config.risk,
            spec=spec,
        )
        stop_after = logical_stop(self.risk, spec=spec)
        adverse_stop_hit = (
            stop_after is not None
            and (low <= stop_after if long else high >= stop_after)
        )
        tightened = stop_after != stop_before
        if target_hit:
            if adverse_stop_hit and tightened:
                self.intrabar_stop = True
                self._close_position(
                    stop_after,
                    now,
                    bar_index,
                    'stair_stop',
                    intrabar_resolution='conservative_stop_first',
                )
            else:
                self._close_position(
                    target,
                    now,
                    bar_index,
                    'take_profit',
                    intrabar_resolution='minute_ohlc_target',
                )
            return
        if adverse_stop_hit and tightened:
            self.intrabar_stop = True
            self._close_position(
                stop_after,
                now,
                bar_index,
                'stair_stop',
                intrabar_resolution='minute_ohlc_path_ambiguous',
            )
            return
        self.risk = protect_logical(
            self.risk,
            price=close,
            time_ns=now,
            risk=self.config.risk,
            spec=spec,
        )
        if self.risk.exit_reason:
            reason = self._stop_reason(self.risk, stage=before_stage)
            self._close_position(
                close,
                now,
                bar_index,
                reason,
                intrabar_resolution='minute_ohlc_close',
            )

    def _target_price(self, state, spec):
        amount = (
            state.initial_r*self.config.risk.take_profit_value
            if self.config.risk.take_profit_mode == 'r_multiple'
            else self.config.risk.take_profit_value
        )
        return state.entry_price+state.side*amount/(
            state.quantity*spec.volume_multiple
        )

    @staticmethod
    def _stop_reason(state, *, stage=None):
        return 'stair_stop' if (state.stage if stage is None else stage) else (
            'initial_stop'
        )

    def _finalize_trade(
        self, *, exit_time_ns, exit_price, reason, final_stop
    ):
        active = self.active
        if active is None or self.risk is None or self.risk.quantity:
            raise _LocalFailure('trade_close_incomplete')
        gross = self.risk.realized_gross
        fees = active['fees']
        self.trades.append({
            'trade_id': active['trade_id'],
            'status': 'closed',
            'direction': active['side'],
            'first_symbol': active['first_symbol'],
            'last_symbol': active['last_symbol'],
            'quantity': active['quantity'],
            'requested_quantity': active['requested_quantity'],
            'entry_time_ns': str(active['entry_time_ns']),
            'entry_price': str(active['entry_price']),
            'exit_time_ns': str(exit_time_ns),
            'exit_price': str(exit_price),
            'initial_stop': str(active['initial_stop']),
            'final_stop': str(final_stop),
            'initial_r': str(self.risk.initial_r),
            'exit_reason': reason,
            'gross_pnl': str(gross),
            'fee': str(fees),
            'net_pnl': str(gross-fees),
            'fill_count': active['fill_count'],
            'entry_plan': active['entry_plan'],
        })
        self.closed_gross += gross
        self.active = None
        self.risk = None
        self.current_symbol = None
        self.last_mark = ZERO

    def _record_fill(self, fill):
        self.fills.append(fill)
        self.fees += self._decimal(fill['fee'])
        if self.active is not None and fill['trade_id'] == self.active['trade_id']:
            self.active['fees'] += self._decimal(fill['fee'])
            self.active['fill_count'] += 1
        self.sequence += 1

    def _fill(
        self,
        *,
        symbol,
        direction,
        offset,
        role,
        volume,
        requested_volume,
        price,
        time_ns,
        execution_bar,
        signal_bar,
        trade_id,
        fee,
        intrabar_resolution=None,
        price_source='bar_price',
    ):
        return {
            'key': f'local-fill-{self.sequence}',
            'order_id': None,
            'direction': direction,
            'offset': offset,
            'role': role,
            'symbol': symbol,
            'volume': int(volume),
            'requested_volume': int(requested_volume),
            'price': str(price),
            'time_ns': int(time_ns),
            'fee': str(fee),
            'trade_id': trade_id,
            'signal_bar': signal_bar,
            'execution_bar': execution_bar,
            'intrabar_resolution': intrabar_resolution,
            'price_source': price_source,
        }

    def _filled_quantity(self, requested, lot_step):
        raw = int(requested*self.engine.fill_fraction)
        if raw >= requested:
            return requested
        return raw-raw % lot_step

    def _commission(self, spec, quantity):
        return spec.commission_per_lot*quantity*self.engine.fee_multiplier

    def _available(self):
        realized = (
            self.risk.realized_gross
            if self.risk is not None
            else ZERO
        )
        return self.initial-self.fees+self.closed_gross+realized

    def _append_equity(self, row, bar_index):
        current_gross = ZERO
        margin = ZERO
        if self.risk is not None and self.risk.quantity:
            spec = self.dataset.specs[self.current_symbol]
            self.last_mark = self._decimal(row.actual_close)
            current_gross = logical_gross(
                self.risk,
                price=self._decimal(row.actual_close),
                spec=spec,
            )
            margin = spec.margin_per_lot*self.risk.quantity
        equity_value = (
            self.initial-self.fees+self.closed_gross+current_gross
        )
        balance = (
            self.initial-self.fees+self.closed_gross
            + (self.risk.realized_gross if self.risk is not None else ZERO)
        )
        self.equity.append({
            'time_ns': str(int(row.time_ns)),
            'balance': str(balance),
            'unrealized_gross': str(current_gross-self.risk.realized_gross)
            if self.risk is not None
            else '0',
            'equity': str(equity_value),
            'margin': str(margin),
            'last_fill': self.fills[-1]['key'] if self.fills else None,
            'bar_index': bar_index,
        })

    def _result(self, status, reason):
        if self.active is not None and self.risk is not None:
            spec = self.dataset.specs[self.current_symbol]
            stop = logical_stop(self.risk, spec=spec)
            current = logical_gross(
                self.risk,
                price=self.last_mark,
                spec=spec,
            )
            self.trades.append({
                'trade_id': self.active['trade_id'],
                'status': 'open',
                'direction': self.active['side'],
                'first_symbol': self.active['first_symbol'],
                'last_symbol': self.active['last_symbol'],
                'quantity': self.active['quantity'],
                'requested_quantity': self.active['requested_quantity'],
                'entry_time_ns': str(self.active['entry_time_ns']),
                'entry_price': str(self.active['entry_price']),
                'exit_time_ns': None,
                'exit_price': None,
                'initial_stop': str(self.active['initial_stop']),
                'final_stop': str(stop),
                'initial_r': str(self.risk.initial_r),
                'exit_reason': None,
                'gross_pnl': str(current),
                'fee': str(self.active['fees']),
                'net_pnl': None,
                'fill_count': self.active['fill_count'],
                'entry_plan': self.active['entry_plan'],
            })
            open_position = self.risk.side*self.risk.quantity
            current_gross = current
        else:
            open_position = 0
            current_gross = ZERO
        final_equity = (
            self.initial-self.fees+self.closed_gross+current_gross
        )
        gross_pnl = (
            self.closed_gross
            + (
                current_gross-self.risk.realized_gross
                if self.risk is not None
                else ZERO
            )
        )
        return LocalRunResult(
            dataset_id=self.dataset.dataset_id,
            config=self.config.public(),
            status=status,
            reason=reason,
            signals=list(self.public_signals),
            fills=list(self.fills),
            trades=list(self.trades),
            equity=list(self.equity),
            rolls=list(self.rolls),
            entry_rejections=list(self.entry_rejections),
            fees=self.fees,
            gross_pnl=gross_pnl,
            final_equity=final_equity,
            closed_trade_count=sum(
                item['status'] == 'closed' for item in self.trades
            ),
            open_position=open_position,
            engine_kind='local_research',
            engine_version='local_research_v1',
            compute_backend='cpu',
            precision=self.config.precision,
            fee_multiplier=self.engine.fee_multiplier,
            profile={
                'elapsed_seconds': time.perf_counter()-self.started,
                'bars_processed': len(self.equity),
                'intrabar_stop_first': self.intrabar_stop,
            },
        )

    @staticmethod
    def _decimal(value):
        return decimal_value(value)

    @staticmethod
    def _date(stamp):
        return pd.Timestamp(
            int(stamp), unit='ns', tz='UTC'
        ).tz_convert('Asia/Shanghai').date()
