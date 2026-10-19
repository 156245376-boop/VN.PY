from dataclasses import asdict
from types import SimpleNamespace

import pytest

from qf.continuous_roll import ContinuousGuard, RollCoordinator, RollState
from qf.safety import Frozen

OLD, NEW = 'SHFE.rb2505', 'SHFE.rb2510'


def advance(c, *, positions=None, pending=None, finished=True, **kw):
    return c.advance(positions=positions or {}, pending_orders=pending or {},
                     task_finished=finished, risk_exit=kw.get('risk_exit'),
                     stop_requested=kw.get('stop_requested', False),
                     mapping=kw.get('mapping', NEW), now_ns=kw.get('now_ns', 20))


def coordinator(lots=2):
    c = RollCoordinator(RollState(), timeout_seconds=1)
    c.request(OLD, NEW, side=1 if lots else 0, lots=lots, now_ns=10)
    return c


def test_no_new_open_until_old_flat_and_cancel_confirmed():
    c = coordinator()
    assert advance(c, positions={OLD: (2, 0)}, finished=False) == [
        {'kind': 'cancel', 'symbol': OLD}]
    assert advance(c, positions={OLD: (2, 0)}, finished=False) == []
    pending = {'o': SimpleNamespace(symbol=OLD, status='ALIVE')}
    assert advance(c, positions={OLD: (2, 0)}, pending=pending) == []
    assert advance(c, positions={OLD: (2, 0)}) == [
        {'kind': 'target', 'symbol': OLD, 'volume': 0, 'role': 'roll_out'}]
    assert advance(c, positions={OLD: (1, 0)}) == []
    assert advance(c, pending=pending) == []
    assert advance(c) == [{'kind': 'cancel', 'symbol': OLD}]
    assert advance(c, finished=False) == []
    assert advance(c) == [
        {'kind': 'target', 'symbol': NEW, 'volume': 2, 'role': 'roll_in'}]
    assert advance(c, positions={NEW: (1, 0)}) == []
    assert advance(c, positions={NEW: (2, 0)}, finished=False) == []
    assert advance(c, positions={NEW: (2, 0)}) == [{'kind': 'complete'}]
    assert c.state.phase == 'idle'
    assert advance(c, positions={NEW: (2, 0)}) == []


@pytest.mark.parametrize('interrupt', [dict(stop_requested=True),
    dict(risk_exit='take_profit'), dict(risk_exit='ma_reverse'),
    dict(mapping='SHFE.rb2601')])
def test_same_update_exit_has_priority_and_never_revives_new_intent(interrupt):
    c = coordinator()
    actions = advance(c, positions={OLD: (2, 0)}, finished=False, **interrupt)
    assert all(a['kind'] == 'cancel' for a in actions)
    assert c.state.phase == 'aborting'
    assert advance(c, positions={OLD: (2, 0)}, finished=False) == []
    actions = advance(c, positions={OLD: (2, 0)})
    assert actions == [{'kind': 'target', 'symbol': OLD, 'volume': 0,
                        'role': 'strategy_close'}]
    assert advance(c, positions={OLD: (1, 0)}) == []
    expected = ([{'kind': 'freeze', 'reason': c.state.reason}] if 'mapping' in interrupt else
                [{'kind': 'complete', 'aborted': True, 'reason': c.state.reason}])
    assert advance(c) == expected
    assert advance(c) == []


def test_flat_switch_has_no_trades():
    c = coordinator(0)
    assert advance(c) == [{'kind': 'cancel', 'symbol': OLD}]
    assert advance(c) == [{'kind': 'complete'}]


def test_partial_new_entry_is_protected_then_aborted_on_timeout():
    c = coordinator()
    advance(c, positions={OLD: (2, 0)})
    advance(c, positions={OLD: (2, 0)})
    advance(c)
    advance(c)
    assert c.state.phase == 'new_enter'
    # 风险计算由连续逻辑交易状态完成；协调器不得把部分仓位当完整移仓。
    assert advance(c, positions={NEW: (1, 0)}) == []
    actions = advance(c, positions={NEW: (1, 0)}, now_ns=2_000_000_010)
    assert actions == [{'kind': 'cancel', 'symbol': OLD},
                       {'kind': 'cancel', 'symbol': NEW}]
    assert advance(c, positions={NEW: (1, 0)}, finished=False) == []
    assert advance(c, positions={NEW: (1, 0)}) == [
        {'kind': 'target', 'symbol': NEW, 'volume': 0, 'role': 'strategy_close'}]
    assert advance(c) == [{'kind': 'freeze', 'reason': 'roll_timeout'}]


def test_state_is_exact_journal_interface_and_invalid_request_rejected():
    assert set(asdict(RollState())) == {'phase', 'old_symbol', 'new_symbol',
        'side', 'requested_lots', 'started_ns', 'reason'}
    c = coordinator()
    with pytest.raises(ValueError):
        c.request(OLD, NEW, side=1, lots=2, now_ns=11)


class Ledger:
    def __init__(self):
        self.state = {'current_symbol': OLD}
        self.positions = {}
    def get(self, k, default=None):
        return self.state.get(k, default)
    def set(self, k, v):
        self.state[k] = v
    def event(self, k):
        pass
    def owned(self):
        return {'owned'}
    def expected_positions(self):
        return self.positions


def test_guard_accepts_only_owned_fills_and_exact_intent():
    ledger = Ledger()
    seen = []
    guard = ContinuousGuard(ledger, coordinator(), fill_handler=seen.append)
    guard.start({}, {}, activate=True)
    guard.authorize_target(OLD, 2)
    guard.before_order(OLD, 'BUY', 'OPEN', 2)
    guard.accept_fill({'key': 'f', 'order_id': 'owned'})
    assert len(seen) == 1
    with pytest.raises(Frozen, match='external_trade'):
        guard.accept_fill({'key': 'bad', 'order_id': 'external'})


@pytest.mark.parametrize('positions', [{OLD: (1, 1)},
    {'SHFE.cu2505': (1, 0)}, {OLD: (1, 0), NEW: (1, 0)}, {OLD: (1, 0)}])
def test_guard_rejects_dual_external_and_ledger_mismatch(positions):
    ledger = Ledger()
    ledger.positions = {k: long-short for k, (long, short) in positions.items() if long or short}
    if positions == {OLD: (1, 0)}:
        ledger.positions = {}
    guard = ContinuousGuard(ledger, coordinator(), fill_handler=lambda _: None)
    guard.start({}, {}, activate=True)
    with pytest.raises(Frozen):
        guard.check(positions, {})


def test_guard_does_not_open_new_while_old_has_position_or_order():
    ledger = Ledger()
    guard = ContinuousGuard(ledger, coordinator(), fill_handler=lambda _: None)
    guard.start({}, {}, activate=True)
    guard.authorize_target(NEW, 2)
    guard.positions = {OLD: (1, 0)}
    with pytest.raises(Frozen):
        guard.before_order(NEW, 'BUY', 'OPEN', 2)
