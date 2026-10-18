import pytest
from test_runtime_safety import order

from qf.journal import Journal
from qf.safety import ExecutionScope, Frozen, Guard


def test_legacy_guard_stays_one_lot_long_only(tmp_path):
    j = Journal.create(tmp_path, 'paper', {})
    g = Guard(j, 'SHFE.rb2505')
    g.start({}, {}, activate=True)
    with pytest.raises(Frozen):
        g.before_order('SHFE.rb2505', 'SELL', 'OPEN', 1)
    j.close()


def test_scoped_guard_counts_pending_open_volume_and_net_short(tmp_path):
    j = Journal.create(tmp_path, 'paper', {})
    g = Guard(j, 'SHFE.rb2505', scope=ExecutionScope(3, True))
    g.start({}, {}, activate=True)
    g.before_order('SHFE.rb2505', 'SELL', 'OPEN', 3)
    j.order('owned', 'SHFE.rb2505', 'SELL', 'OPEN', 3)
    g.orders = {'owned': order('owned', left=3)}
    with pytest.raises(Frozen):
        g.before_order('SHFE.rb2505', 'SELL', 'OPEN', 3)
    g.enabled = True
    g.positions = {'SHFE.rb2505': (0, 3)}
    g.orders = {}
    g.before_order('SHFE.rb2505', 'BUY', 'CLOSE', 3)
    with pytest.raises(Frozen):
        g.before_order('SHFE.rb2505', 'BUY', 'OPEN', 1)
    j.close()


def test_scope_allows_serial_today_and_yesterday_closes(tmp_path):
    j = Journal.create(tmp_path, 'paper', {})
    g = Guard(j, 'SHFE.rb2505', scope=ExecutionScope(3, True))
    g.start({}, {}, activate=True)
    g.positions = {'SHFE.rb2505': (2, 0)}
    g.before_order('SHFE.rb2505', 'SELL', 'CLOSETODAY', 1)
    g.positions = {'SHFE.rb2505': (1, 0)}
    g.before_order('SHFE.rb2505', 'SELL', 'CLOSE', 1)
    j.close()
