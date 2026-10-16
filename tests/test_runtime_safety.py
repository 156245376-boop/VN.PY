from types import SimpleNamespace

import pytest

from qf.journal import Journal
from qf.safety import Frozen, Guard, settle_stop


def order(oid="o1", left=1, status="ALIVE", error=False):
    return SimpleNamespace(order_id=oid, volume_left=left, status=status, is_error=error)


def test_guard_rejects_dual_positions_dirty_account_and_unknown_orders(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    g = Guard(j, "SHFE.rb2610")
    with pytest.raises(Frozen):
        g.start({"x": (1, 1)}, {}, activate=True)
    with pytest.raises(Frozen):
        g.start({}, {"o1": order()}, activate=True)
    g.start({}, {}, activate=True)
    with pytest.raises(Frozen):
        g.check({"SHFE.rb2610": (0, 0)}, {"external": order("external")})
    assert not g.enabled
    j.close()


def test_guard_partial_fill_is_not_success_and_unknown_fill_freezes(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    g = Guard(j, "SHFE.rb2610")
    g.start({}, {}, activate=True)
    g.before_order("SHFE.rb2610", "BUY", "OPEN", 1)
    j.order("owned", "SHFE.rb2610", "BUY", "OPEN", 1)
    g.check({"SHFE.rb2610": (0, 0)}, {"owned": order("owned", left=1)})
    assert g.enabled
    with pytest.raises(Frozen):
        g.accept_fill({"key": "foreign", "order_id": "foreign"})
    assert not g.enabled
    j.close()


def test_guard_rejects_bypassing_one_lot_or_sending_after_freeze(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    g = Guard(j, "SHFE.rb2610")
    g.start({}, {}, activate=True)
    with pytest.raises(Frozen):
        g.before_order("SHFE.rb2610", "BUY", "OPEN", 2)
    with pytest.raises(Frozen):
        g.before_order("SHFE.rb2610", "BUY", "OPEN", 1)
    j.close()


def test_unclean_restart_cannot_activate_and_duplicate_fill_is_not_reapplied(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    g = Guard(j, "SHFE.rb2610")
    with pytest.raises(Frozen):
        g.start({}, {}, activate=True, resume=True)
    assert not g.enabled
    j.close()


def test_stop_waits_for_task_and_order_confirmation_without_flattening():
    events = []
    task = SimpleNamespace(cancel=lambda: events.append("cancel"),
                           is_finished=lambda: len(events) >= 3)
    orders = {"owned": order("owned")}

    class Api:
        def wait_update(self, deadline):
            events.append("wait")
            if len(events) >= 3:
                orders["owned"].status = "FINISHED"

    assert settle_stop(Api(), task, orders, {"owned"}, 1) is True
    assert events == ["cancel", "wait", "wait"]


def test_stop_timeout_preserves_unconfirmed_status():
    task = SimpleNamespace(cancel=lambda: None, is_finished=lambda: False)
    api = SimpleNamespace(wait_update=lambda deadline: None)
    assert settle_stop(api, task, {}, set(), 0) is False


def test_clean_resume_checks_partial_intent_and_rejected_owned_order(tmp_path):
    from datetime import date
    j = Journal.create(tmp_path, "paper", {})
    j.set("status", "stopped")
    j.set("calendar_date", str(date.today()))
    j.signal(120, 1)
    g = Guard(j, "SHFE.rb2610")
    with pytest.raises(Frozen, match="resume_incomplete"):
        g.start({}, {}, activate=True, resume=True)
    j.applied(120)
    j.set("status", "stopped")
    g.start({}, {}, activate=True, resume=True)
    j.order("o1", "SHFE.rb2610", "BUY", "OPEN", 1)
    with pytest.raises(Frozen, match="order_rejected"):
        g.check({}, {"o1": order(status="FINISHED", error=True)})
    assert not g.enabled
    j.close()


def test_fill_idempotence_reconciles_position_and_zero_net_dual_position_freezes(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    j.order("o1", "SHFE.rb2610", "BUY", "OPEN", 1)
    g = Guard(j, "SHFE.rb2610")
    fill = {"key": "trade1", "order_id": "o1", "symbol": "SHFE.rb2610", "direction": "BUY",
            "offset": "OPEN", "volume": 1, "price": 3300., "time_ns": 60}
    g.accept_fill(fill)
    g.accept_fill(fill)
    assert j.expected_position() == 1
    g.check({"SHFE.rb2610": (1, 0)}, {"o1": order(status="FINISHED", left=0)})
    with pytest.raises(Frozen):
        g.check({"SHFE.rb2610": (1, 1)}, {})
    j.close()


def test_external_order_cancelled_between_updates_still_freezes(tmp_path):
    j = Journal.create(tmp_path, "paper", {})
    g = Guard(j, "SHFE.rb2610")
    g.start({}, {"old": order("old", status="FINISHED")}, activate=True)
    with pytest.raises(Frozen, match="external_order"):
        g.check({}, {"old": order("old", status="FINISHED"),
                     "new": order("new", status="FINISHED")})
    j.close()
