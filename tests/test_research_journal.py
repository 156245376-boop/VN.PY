import sqlite3
from dataclasses import replace

import pytest
from research_helpers import config_data
from test_trade_risk import entered

from qf.research_journal import ResearchJournal, research_trade_key
from qf.trade_risk import close_trade_fills, empty_risk


def fill(**changes):
    value = dict(key='sdk-1', order_id='order-1', symbol='SHFE.rb2505', direction='BUY',
                 offset='OPEN', volume=2, price=1000, time_ns=10)
    return value | changes


def journal(root):
    return ResearchJournal.create(root, 'backtest', config_data())


def test_fill_risk_and_exit_intent_commit_atomically(tmp_path):
    j = journal(tmp_path)
    j.db.execute("CREATE TRIGGER block_event BEFORE INSERT ON risk_events "
                 "BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        j.commit_update('fill-1', time_ns=10, kind='fill', payload={}, risk_state=entered(),
                        fills=[fill()], target=2)
    assert j.expected_position() == 0
    assert j.load_risk() == empty_risk()
    j.db.execute('DROP TRIGGER block_event')
    assert j.commit_update('fill-1', time_ns=10, kind='fill', payload={},
                           risk_state=entered(), fills=[fill()], target=2)
    assert not j.commit_update('fill-2', time_ns=10, kind='fill', payload={},
                               risk_state=entered(quantity=4), fills=[fill()])
    assert j.expected_position() == 2
    assert j.load_risk().quantity == 2
    assert research_trade_key(fill()) != research_trade_key(fill(time_ns=86400000000010))
    j.close()


def test_two_protection_events_in_one_minute_are_retained(tmp_path):
    j = journal(tmp_path)
    for stage in (1, 2):
        j.commit_update(f'quote-{stage}', time_ns=10+stage, kind='protection',
                        payload={}, risk_state=replace(entered(), stage=stage), fills=[])
    assert len(j.load_replay(offset=0, limit=100)['risk_events']) == 2
    assert j.load_risk().stage == 2
    j.close()


def test_close_fills_only_reduce_opposite_direction_and_do_not_change_initial_r():
    state = entered()
    half = close_trade_fills(state, [fill(direction='SELL', offset='CLOSE', volume=1)])
    assert half.quantity == 1 and half.initial_r == 1000
    with pytest.raises(ValueError):
        close_trade_fills(state, [fill(direction='SELL', offset='OPEN')])


def test_saved_completed_bars_are_not_overwritten_by_forming_data(tmp_path):
    j = journal(tmp_path)
    row = dict(datetime=100, open=1, high=3, low=1, close=2, volume=10, close_oi=5)
    j.capture_bars('SHFE.rb2505', 60, [row])
    j.capture_bars('SHFE.rb2505', 60, [row | {'close': 999}])
    assert j.load_replay(offset=0, limit=100)['bars'][0]['close'] == 2
    j.close()


def test_forming_snapshot_can_complete_without_overwriting_final(tmp_path):
    j = journal(tmp_path)
    row = dict(datetime=100, open=1, high=3, low=1, close=2, volume=10, close_oi=5)
    j.capture_bars('SHFE.rb2505', 60, [row], completed=False)
    j.capture_bars('SHFE.rb2505', 60, [row | {'close': 3}], completed=True)
    j.capture_bars('SHFE.rb2505', 60, [row], completed=False)
    saved = j.load_replay(offset=0, limit=100)['bars'][0]
    assert saved['completed'] is True and saved['close'] == 3
    j.close()
