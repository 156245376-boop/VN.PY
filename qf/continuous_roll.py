"""串行移仓：动作仅由运行器交给 TargetPosTask，取消确认不等于平仓。"""

from dataclasses import dataclass, replace

from qf.safety import Frozen


@dataclass(frozen=True)
class RollState:
    phase: str = 'idle'
    old_symbol: str | None = None
    new_symbol: str | None = None
    side: int = 0
    requested_lots: int = 0
    started_ns: int = 0
    reason: str | None = None


class RollCoordinator:
    def __init__(self, state, *, timeout_seconds=60):
        self.state = state
        self.timeout_ns = int(timeout_seconds * 1_000_000_000)
        self._sent = set()
        self._old_exit_cancelled = False

    def request(self, old_symbol, new_symbol, *, side, lots, now_ns):
        if (self.state.phase != 'idle' or not old_symbol or not new_symbol
                or old_symbol == new_symbol or type(lots) is not int or lots < 0
                or type(side) is not int or side not in (-1, 0, 1)
                or (lots == 0) != (side == 0) or type(now_ns) is not int or now_ns <= 0):
            raise ValueError('移仓请求无效或已有移仓未结束')
        self.state = RollState('old_cancel', old_symbol, new_symbol, side, lots, now_ns)
        self._sent.clear()
        self._old_exit_cancelled = False

    def _once(self, key, actions):
        if key in self._sent:
            return []
        self._sent.add(key)
        return actions

    def advance(self, *, positions, pending_orders, task_finished, risk_exit,
                stop_requested, mapping, now_ns):
        s = self.state
        if s.phase in ('idle', 'frozen'):
            return []
        symbols = (s.old_symbol, s.new_symbol)
        done = (all(task_finished.get(sym, True) for sym in symbols)
                if isinstance(task_finished, dict) else task_finished)
        pending = any(o.status != 'FINISHED' for o in pending_orders.values())
        reason = ('stop_requested' if stop_requested else
                  str(risk_exit) if risk_exit else
                  'roll_mapping_changed' if mapping != s.new_symbol else
                  'roll_timeout' if now_ns-s.started_ns > self.timeout_ns else None)
        if reason and s.phase != 'aborting':
            self.state = s = replace(s, phase='aborting', reason=reason)
        if s.phase == 'aborting':
            actions = self._once('abort_cancel', [
                {'kind': 'cancel', 'symbol': sym} for sym in symbols])
            if actions:
                return actions
            if not done or pending:
                return []
            held = [(sym, positions.get(sym, (0, 0))) for sym in symbols]
            actions = []
            for sym, (long, short) in held:
                if long or short:
                    actions += self._once(('abort_flat', sym), [
                        {'kind': 'target', 'symbol': sym, 'volume': 0,
                         'role': 'strategy_close'}])
            if actions or any(long or short for _, (long, short) in held):
                return actions
            self.state = replace(s, phase='frozen')
            return [{'kind': 'freeze', 'reason': s.reason}]
        if s.phase == 'old_cancel':
            actions = self._once('old_cancel', [{'kind': 'cancel', 'symbol': s.old_symbol}])
            if actions:
                return actions
            if not done or pending:
                return []
            if s.requested_lots == 0:
                self.state = replace(s, phase='idle')
                return [{'kind': 'complete'}]
            self.state = replace(s, phase='old_exit')
            return [{'kind': 'target', 'symbol': s.old_symbol, 'volume': 0,
                     'role': 'roll_out'}]
        if s.phase == 'old_exit':
            if any(positions.get(s.old_symbol, (0, 0))) or pending:
                return []
            if not self._old_exit_cancelled:
                self._old_exit_cancelled = True
                return [{'kind': 'cancel', 'symbol': s.old_symbol}]
            if not done:
                return []
            self.state = replace(s, phase='new_enter')
            return [{'kind': 'target', 'symbol': s.new_symbol,
                     'volume': s.side*s.requested_lots, 'role': 'roll_in'}]
        long, short = positions.get(s.new_symbol, (0, 0))
        if (long-short == s.side*s.requested_lots and not pending and done):
            self.state = replace(s, phase='idle')
            return [{'kind': 'complete'}]
        return []


class ContinuousGuard:
    def __init__(self, journal, coordinator, *, fill_handler):
        self.journal, self.coordinator = journal, coordinator
        self.fill_handler = fill_handler
        self.enabled = False
        self.positions, self.orders, self.targets = {}, {}, {}
        self.baseline_orders = set()

    def freeze(self, code):
        self.enabled = False
        self.journal.set('status', 'frozen')
        self.journal.set('reason', code)
        self.journal.event(code)
        raise Frozen(code)

    def start(self, positions, orders, *, activate, resume=False):
        if resume:
            self.freeze('continuous_resume_not_supported')
        if any(long or short for long, short in positions.values()):
            self.freeze('new_run_requires_flat_account')
        if any(o.status != 'FINISHED' for o in orders.values()):
            self.freeze('new_run_requires_no_orders')
        self.baseline_orders = set(orders)
        self.positions, self.orders = positions, orders
        self.enabled = activate

    def _allowed(self):
        s = self.coordinator.state
        if s.phase != 'idle':
            return {s.old_symbol, s.new_symbol}
        return {self.journal.get('current_symbol')}

    def authorize_target(self, symbol, volume):
        if symbol not in self._allowed() or type(volume) is not int:
            self.freeze('order_outside_scope')
        self.targets[symbol] = volume

    def check(self, positions, orders):
        self.positions, self.orders = positions, orders
        actual = {}
        for symbol, (long, short) in positions.items():
            if (type(long) is not int or type(short) is not int or long < 0 or short < 0
                    or (long and short) or ((long or short) and symbol not in self._allowed())):
                self.freeze('unexpected_position')
            if long or short:
                actual[symbol] = long-short
        if len(actual) > 1:
            self.freeze('concurrent_contract_exposure')
        if actual != self.journal.expected_positions():
            self.freeze('position_trade_mismatch')
        owned = self.journal.owned()
        for oid, order in orders.items():
            if oid not in owned and (oid not in self.baseline_orders or order.status != 'FINISHED'):
                self.freeze('external_order')
            if oid in owned and order.is_error:
                self.freeze('order_rejected')

    def before_order(self, symbol, direction, offset, volume):
        if not self.enabled:
            self.freeze('execution_disabled')
        if (symbol not in self._allowed() or direction not in ('BUY', 'SELL')
                or offset not in ('OPEN', 'CLOSE', 'CLOSETODAY')
                or type(volume) is not int or volume <= 0 or symbol not in self.targets):
            self.freeze('order_outside_scope')
        if any(o.status != 'FINISHED' for o in self.orders.values()):
            self.freeze('order_still_pending')
        long, short = self.positions.get(symbol, (0, 0))
        target = self.targets[symbol]
        side = 1 if direction == 'BUY' else -1
        if offset == 'OPEN':
            s = self.coordinator.state
            if (any(long_n or short_n for sym, (long_n, short_n) in self.positions.items()
                    if sym != symbol)
                    or (symbol == s.new_symbol and s.phase != 'new_enter'
                        and s.phase != 'idle')
                    or (short if side > 0 else long)
                    or target*side <= 0 or (long+short+volume > abs(target))):
                self.freeze('order_position_limit')
        elif volume > (long if side < 0 else short) or target*side < 0:
            self.freeze('order_position_limit')

    def accept_fill(self, fill):
        if fill['order_id'] not in self.journal.owned():
            self.freeze('external_trade')
        self.fill_handler(fill)
