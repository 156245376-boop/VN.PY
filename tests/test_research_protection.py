from dataclasses import asdict

import pytest
from research_helpers import pivot_config_data

from qf.research_config import validate_research_config
from qf.research_journal import ResearchJournal, dumps, research_trade_key
from qf.research_protection import protection_window, trade_explanation
from qf.trade_risk import RiskState


def journal(tmp_path):
    cfg = validate_research_config(pivot_config_data())
    return ResearchJournal.create(tmp_path, 'backtest', cfg.public())


def insert_event(j, event_id, stamp, kind, payload, risk):
    with j.db:
        j.db.execute('INSERT INTO risk_events VALUES (?,?,?,?,?,?)', (
            event_id, stamp, kind, dumps(payload), dumps(asdict(risk)), None))


def held(stop=3284, stage=0):
    return RiskState('trade-1', 1, 1, 3301, 850, True, stage, stop, 0, 100, 100, None)


def signal_payload():
    return {
        'signal': {'direction': 1, 'bar_start_ns': 90, 'fast_current': 3305,
                   'slow_current': 3290},
        'entry_plan': {
            'side': 1, 'lots': 1, 'reference_price': '3301',
            'stop_price': '3284', 'distance_ticks': '17', 'planned_r': '170',
            'pivot': {'kind': 'low', 'price': '3284', 'bar_start_ns': 60,
                      'confirmed_ns': 120, 'left': 5, 'right': 5},
        },
    }


def test_protection_carries_left_seed_and_open_tail(tmp_path):
    j = journal(tmp_path)
    try:
        insert_event(j, 'signal', 90, 'signal', signal_payload(), held())
        insert_event(j, 'fill', 100, 'fill', {}, held())
        insert_event(j, 'protection', 110, 'protection', {}, held(stage=1, stop=3302))

        result = protection_window(j.db, first_ns=150, as_of_ns=200,
                                   series='actual', symbol='SHFE.rb2505')
        active = [s for s in result['segments'] if s['kind'] == 'active']
        initial = [s for s in result['segments'] if s['kind'] == 'initial']
        assert len(active) == 1
        assert active[0]['actual_price'] == '3302'
        assert active[0]['end_ns'] == '200'
        assert len(initial) == 1 and initial[0]['actual_price'] == '3284'
        assert all(int(segment['end_ns']) <= 200 for segment in result['segments'])
    finally:
        j.close()


def test_same_bar_updates_and_close_break_trace(tmp_path):
    j = journal(tmp_path)
    try:
        insert_event(j, 'signal', 90, 'signal', signal_payload(), held())
        insert_event(j, 'fill', 100, 'fill', {}, held())
        insert_event(j, 'p1', 110, 'protection', {}, held(stage=1, stop=3302))
        insert_event(j, 'p2', 110, 'protection', {}, held(stage=2, stop=3310))
        closed = RiskState('trade-1', 1, 0, 3301, 850, True, 2, 3310, 0, 130, 130,
                           'take_profit')
        insert_event(j, 'close', 120, 'fill', {}, closed)

        result = protection_window(j.db, first_ns=0, as_of_ns=200,
                                   series='actual', symbol='SHFE.rb2505')
        active = [s for s in result['segments'] if s['kind'] == 'active']
        assert [s['actual_price'] for s in active] == ['3284', '3302', '3310']
        assert active[-1]['end_ns'] == '120'
        assert all(s['end_ns'] != '200' for s in active)
    finally:
        j.close()


def test_trade_explanation_uses_original_signal_and_pivot(tmp_path):
    j = journal(tmp_path)
    fill = dict(key='fill-1', order_id='o1', symbol='SHFE.rb2505', direction='BUY',
                offset='OPEN', volume=1, price=3301, time_ns=100)
    try:
        insert_event(j, 'signal', 90, 'signal', signal_payload(), held())
        j.commit_update('fill-event', time_ns=100, kind='fill', payload={},
                        risk_state=held(), fills=[fill])
        details = trade_explanation(j.db, fill_key=research_trade_key(fill))
        assert details['fill']['price'] == 3301
        assert details['entry_plan']['stop_price'] == '3284'
        assert details['pivot']['price'] == '3284'
        assert details['initial_r'] == '850'
        assert details['risk_events'][-1]['stop_price'] == '3284'
    finally:
        j.close()


@pytest.mark.parametrize('price', ['0', '-4'])
def test_nonpositive_display_price_is_kept(tmp_path, price):
    j = journal(tmp_path)
    try:
        state = held(stage=1, stop=3302)
        insert_event(j, 'fill', 100, 'fill', {}, state)
        offset = 3302 if price == '0' else 3306
        j.db.execute("INSERT OR REPLACE INTO state VALUES ('signal_offset',?)",
                     (dumps(offset),))
        result = protection_window(j.db, first_ns=0, as_of_ns=101,
                                   series='signal', symbol='SHFE.rb2505')
        assert result['segments'][0]['display_price'] == price
    finally:
        j.close()
