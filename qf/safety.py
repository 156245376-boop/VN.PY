import time
from datetime import date


class Frozen(ValueError):
    """只允许预定义业务原因，禁止传入 SDK 原始异常。"""


class Guard:
    def __init__(self, journal, symbol):
        self.journal = journal
        self.symbol = symbol
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
            if short or long < 0 or long > 1 or (symbol != self.symbol and long):
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
        if (symbol != self.symbol or type(volume) is not int or volume != 1
                or (direction, offset) not in
                {("BUY", "OPEN"), ("SELL", "CLOSE"), ("SELL", "CLOSETODAY")}):
            self.freeze("order_outside_scope")
        long, short = self.positions.get(symbol, (0, 0))
        if short or (offset == "OPEN" and long) or (offset != "OPEN" and long < volume):
            self.freeze("order_position_limit")
        if any(o.status != "FINISHED" for o in self.orders.values()):
            self.freeze("order_still_pending")

    def accept_fill(self, fill):
        if fill["key"] in self.baseline:
            return
        if fill["order_id"] not in self.journal.owned():
            self.freeze("external_trade")
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
