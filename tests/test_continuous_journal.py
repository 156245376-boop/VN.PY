import importlib
import sqlite3
from dataclasses import asdict
from decimal import Decimal as D

import pytest
from test_continuous_config import continuous_data
from test_continuous_risk import spec
from test_continuous_series import BASE, MINUTE, row
from test_research_journal import fill

from qf.continuous_risk import LogicalRisk
from qf.research_config import public_values
from qf.research_journal import integrity_manifest


def journal(root):
    cls = importlib.import_module('qf.continuous_journal').ContinuousJournal
    return cls.create(root, 'backtest', continuous_data() | {'bar_seconds': 60})


def state():
    return LogicalRisk(trade_id='logical-1', side=1, quantity=1, entry_price=D(100),
                       initial_r=D(100), floor_gross=D(-100), sealed=True,
                       first_offset_amount=D(10), last_fill_ns=10)


def rolling():
    return dict(phase='idle', old_symbol=None, new_symbol=None, side=0,
                requested_lots=0, started_ns=0, reason=None)


def arguments():
    return dict(time_ns=10, kind='fill', payload=dict(role='strategy_open', symbol='SHFE.rb2505'),
                logical_risk=state(), roll_state=rolling(),
                fills=[fill(volume=1, price=100)], target=1)


def test_fill_risk_roll_state_commit_is_atomic_and_idempotent(tmp_path):
    j = journal(tmp_path)
    try:
        j.record_spec('SHFE.rb2505', spec())
        j.db.execute("CREATE TRIGGER block_event BEFORE INSERT ON risk_events "
                     "BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with pytest.raises(sqlite3.IntegrityError):
            j.commit_continuous('entry', **arguments())
        assert j.expected_positions() == {}
        assert j.get('logical_risk') == public_values(asdict(LogicalRisk()))
        assert j.db.execute('SELECT count(*) FROM logical_fills').fetchone()[0] == 0
        j.db.execute('DROP TRIGGER block_event')
        assert j.commit_continuous('entry', **arguments())
        assert j.expected_positions() == {'SHFE.rb2505': 1}
        assert j.commit_continuous('entry-duplicate', **arguments()) is False
        assert j.db.execute('SELECT count(*) FROM fills').fetchone()[0] == 1
        assert j.get('logical_risk')['initial_r'] == '100'
        link = j.db.execute('SELECT role,fee FROM logical_fills').fetchone()
        assert link == ('strategy_open', '2')
    finally:
        j.close()


def seed(j):
    series = importlib.import_module('qf.continuous_series').SignalSeries(60, max_window=20)
    evidence = series.switch(old_symbol=None, new_symbol='SHFE.rb2505',
        detected_ns=BASE, old_rows=[], new_rows=[])
    j.record_mapping(evidence)
    j.record_spec('SHFE.rb2505', spec())
    j.capture_actual('SHFE.rb2505', 60, [row(0, 100)])
    j.capture_actual('SHFE.rb2510', 60, [row(0, 200)])
    bar = series.append(symbol='SHFE.rb2505', row=row(0, 100), completed_at_ns=BASE+MINUTE)
    assert j.capture_signal(bar)
    assert not j.capture_signal(bar)
    j.commit_continuous('entry', **arguments())


@pytest.mark.parametrize('table,column,value', [
    ('signal_bars', 'data', '{}'), ('main_changes', 'data', '{}'),
    ('contract_specs', 'data', '{}'), ('logical_fills', 'role', 'roll_in'),
    ('roll_events', 'data', '{}')])
def test_manifest_covers_continuous_evidence(tmp_path, table, column, value):
    j = journal(tmp_path)
    try:
        seed(j)
        j.checkpoint_integrity()
        before = j.get('research_integrity')
        assert integrity_manifest(j.db) == before
        with j.db:
            j.db.execute(f'UPDATE {table} SET {column}=?', (value,))
        assert integrity_manifest(j.db) != before
    finally:
        j.close()


def test_actual_and_signal_series_have_separate_identity_and_counts(tmp_path):
    j = journal(tmp_path)
    try:
        seed(j)
        assert j.db.execute('SELECT count(*) FROM research_bars').fetchone()[0] == 2
        assert j.get('signal_count') == 1 and j.get('fill_count') == 1
        assert j.db.execute('SELECT seq,time_ns FROM signal_bars').fetchone() == (0, BASE)
    finally:
        j.close()


def test_unknown_payload_and_changed_duplicate_fill_are_rejected(tmp_path):
    j = journal(tmp_path)
    try:
        j.record_spec('SHFE.rb2505', spec())
        args = arguments()
        with pytest.raises(ValueError):
            j.commit_continuous('private', **(args | {'payload': {'password': 'private'}}))
        assert j.expected_positions() == {}
        j.commit_continuous('entry', **args)
        with pytest.raises(ValueError):
            changed = args | {'fills': [fill(volume=1, price=101)]}
            j.commit_continuous('corrupted-duplicate', **changed)
    finally:
        j.close()


@pytest.mark.parametrize('bad', [dict(requested_lots=True), dict(requested_lots=-1),
    dict(side=5), dict(started_ns=-1), dict(old_symbol='SHFE.cu2505')])
def test_invalid_roll_control_state_cannot_be_recorded(tmp_path, bad):
    j = journal(tmp_path)
    try:
        args = arguments() | {'fills': [], 'kind': 'intent', 'logical_risk': LogicalRisk()}
        with pytest.raises(ValueError):
            j.commit_continuous('bad-control', **(args | {'roll_state': rolling() | bad}))
    finally:
        j.close()


def test_nested_raw_fields_are_whitelisted(tmp_path):
    j = journal(tmp_path)
    try:
        series = importlib.import_module('qf.continuous_series').SignalSeries(60, max_window=20)
        series.switch(old_symbol=None, new_symbol='SHFE.rb2505', detected_ns=BASE,
                      old_rows=[], new_rows=[])
        bar = series.append(symbol='SHFE.rb2505', row=row(0, 100),
                            completed_at_ns=BASE+MINUTE)
        bar['raw']['password'] = 'private'
        with pytest.raises(ValueError):
            j.capture_signal(bar)
    finally:
        j.close()


def test_roll_gap_requires_matching_saved_reference_prices(tmp_path):
    j = journal(tmp_path)
    try:
        seed(j)
        evidence = dict(changed=True, old_symbol='SHFE.rb2505', new_symbol='SHFE.rb2510',
            detected_ns=BASE+MINUTE, reference_ns=BASE, previous_offset=0, offset=101)
        with pytest.raises(ValueError):
            j.record_mapping(evidence)
        assert j.record_mapping(evidence | {'offset': 100})
        assert j.get('signal_offset') == 100
    finally:
        j.close()
