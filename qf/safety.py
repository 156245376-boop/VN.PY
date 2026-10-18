import time
from dataclasses import dataclass
from datetime import date


class Frozen(ValueError):
    """只允许预定义业务原因，禁止传入 SDK 原始异常。"""


@dataclass(frozen=True)
class ExecutionScope:
    max_lots: int
    allow_short: bool

    def __post_init__(self):
        if (type(self.max_lots) is not int or self.max_lots < 1
                or type(self.allow_short) is not bool):
            raise ValueError('执行范围无效')


class Guard:
    def __init__(self, journal, symbol, *, scope=None, fill_handler=None):
        self.journal = journal
        self.symbol = symbol
        self.scope = scope
        self.fill_handler = fill_handler
        self.enabled = False
        self.positions = {}
        self.orders = {}
        self.baseline = set(journal.get("baseline_trades", []))
        self.baseline_orders = set(journal.get("baseline_orders", []))

    def freeze(self, code):
        self.enabled = False
        self.journal.set("reason", code)
        self.journal.set("status", "frozen")
        self.journal.event(code)
        raise Frozen(code)

    def start(self, positions, orders, *, activate, resume=False):
        self.positions, self.orders = positions, orders
        if not resume:
            self.baseline_orders = set(orders)
            self.journal.set("baseline_orders", sorted(self.baseline_orders))
        if resume:
            if (self.journal.get("status") != "stopped"
                    or self.journal.get("calendar_date") != str(date.today())
                    or self.journal.db.execute("SELECT count(*) FROM signals WHERE applied=0")
                    .fetchone()[0]):
                self.freeze("resume_incomplete")
            self.check(positions, orders)
            if any(o.status != "FINISHED" for o in orders.values()):
                self.freeze("resume_pending_orders")
        elif any(long or short for long, short in positions.values()):
            self.freeze("new_run_requires_flat_account")
        elif any(o.status != "FINISHED" for o in orders.values()):
            self.freeze("new_run_requires_no_orders")
        self.enabled = activate
        self.journal.set("calendar_date", str(date.today()))
        self.journal.set("status", "active" if activate else "observing")

    def check(self, positions, orders):
        self.positions, self.orders = positions, orders
        for symbol, (long, short) in positions.items():
            maximum = self.scope.max_lots if self.scope else 1
            if (long < 0 or short < 0 or long > maximum or short > maximum
                    or (short and not (self.scope and self.scope.allow_short))
                    or (long and short) or (symbol != self.symbol and (long or short))):
                self.freeze("unexpected_position")
        owned = self.journal.owned()
        for oid, order in orders.items():
            if (oid not in owned and
                    (oid not in self.baseline_orders or order.status != "FINISHED")):
                self.freeze("external_order")
            if oid in owned and order.is_error:
                self.freeze("order_rejected")
        long, short = positions.get(self.symbol, (0, 0))
        if long - short != self.journal.expected_position():
            self.freeze("position_trade_mismatch")

    def before_order(self, symbol, direction, offset, volume):
        if not self.enabled:
            self.freeze("execution_disabled")
        if self.scope:
            return self._scoped_order(symbol, direction, offset, volume)
        if (symbol != self.symbol or type(volume) is not int or volume != 1
                or (direction, offset) not in
                {("BUY", "OPEN"), ("SELL", "CLOSE"), ("SELL", "CLOSETODAY")}):
            self.freeze("order_outside_scope")
        long, short = self.positions.get(symbol, (0, 0))
        if short or (offset == "OPEN" and long) or (offset != "OPEN" and long < volume):
            self.freeze("order_position_limit")
        if any(o.status != "FINISHED" for o in self.orders.values()):
            self.freeze("order_still_pending")

    def _scoped_order(self, symbol, direction, offset, volume):
        if (symbol != self.symbol or direction not in ('BUY', 'SELL')
                or offset not in ('OPEN', 'CLOSE', 'CLOSETODAY')
                or type(volume) is not int or not 1 <= volume <= self.scope.max_lots):
            self.freeze('order_outside_scope')
        if any(o.status != 'FINISHED' for o in self.orders.values()):
            self.freeze('order_still_pending')
        long, short = self.positions.get(symbol, (0, 0))
        if offset == 'OPEN':
            side = 1 if direction == 'BUY' else -1
            existing, opposite = (long, short) if side > 0 else (short, long)
            target = self.journal.get('last_target')
            if (opposite or existing+volume > self.scope.max_lots
                    or (side < 0 and not self.scope.allow_short)
                    or (target is not None and
                        (target*side <= 0 or existing+volume > abs(target)))):
                self.freeze('order_position_limit')
        elif volume > (long if direction == 'SELL' else short):
            self.freeze('order_position_limit')

    def accept_fill(self, fill):
        if fill["key"] in self.baseline:
            return
        if fill["order_id"] not in self.journal.owned():
            self.freeze("external_trade")
        if self.fill_handler:
            self.fill_handler(fill)
        else:
            self.journal.fill(fill)


def settle_stop(api, task, orders, owned, timeout):
    """仅撤销执行任务及其挂单；不创建平仓目标，不把超时视作确认。"""
    if task is None:
        return not any(o.status != "FINISHED" for k, o in orders.items() if k in owned)
    task.cancel()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if task.is_finished() and not any(o.status != "FINISHED" for k, o in orders.items()
                                           if k in owned):
            return True
        api.wait_update(deadline=time.time() + min(1, max(0, end - time.monotonic())))
    return False
