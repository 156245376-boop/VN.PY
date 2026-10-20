import hashlib
import json
import sqlite3
from types import SimpleNamespace as NS

import pytest
from continuous_sdk import ContinuousSdkFixture
from pivot_sdk import sdk_for_pivot
from research_helpers import pivot_config_data
from test_continuous_runtime import config as continuous_config

from qf.research_account import (
    account_snapshot,
    account_window,
    compact_account_snapshot,
    costs_reconciled,
    enable_account_evidence,
    read_account,
    save_account,
)
from qf.research_config import validate_research_config
from qf.research_journal import ResearchJournal, research_trade_key
from qf.research_runtime import execute_research
from qf.trade_risk import RiskState


class Api:
    def __init__(self):
        self.account = NS(balance=100000, float_profit=0, available=95000,
                          commission=3, password='private-password')
        self.positions = {'SHFE.rb2505': NS(pos_long=10, pos_short=0,
                                           open_price_long=3300, float_profit=0,
                                           margin=30000)}

    def get_account(self):
        return self.account

    def get_position(self):
        return self.positions

    def get_order(self):
        return {}

    def get_trade(self):
        return {}


def journal(tmp_path):
    cfg = validate_research_config(pivot_config_data())
    return ResearchJournal.create(tmp_path, 'backtest', cfg.public())


def test_account_fields_zero_missing_and_no_credentials(tmp_path):
    j = journal(tmp_path)
    try:
        enable_account_evidence(j)
        snapshot = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '10', 'roll_commission': '4',
            'actual_fill_count': 161, 'closed_trade_count': 80,
            'open_position': 10,
        })
        assert snapshot['summary']['balance'] == 100000
        assert snapshot['summary']['float_profit'] == 0
        assert snapshot['summary']['margin'] is None
        assert snapshot['summary']['commission'] == 3
        assert snapshot['summary']['commission_total'] == '10'
        assert snapshot['summary']['actual_fill_count'] == 161
        assert snapshot['summary']['closed_trade_count'] == 80
        assert snapshot['summary']['open_position'] == 10
        assert 'private-password' not in json.dumps(snapshot)
    finally:
        j.close()


def test_bar_snapshot_can_store_summary_without_repeating_detail_rows(tmp_path):
    j = journal(tmp_path)
    try:
        enable_account_evidence(j)
        snapshot = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '1', 'roll_commission': '0',
            'actual_fill_count': 1, 'closed_trade_count': 0, 'open_position': 10})
        compact = compact_account_snapshot(snapshot)
        summary_only = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '1', 'roll_commission': '0',
            'actual_fill_count': 1, 'closed_trade_count': 0, 'open_position': 10},
            details=False)
        assert compact['summary'] == snapshot['summary']
        assert compact['positions'] == [] and compact['orders'] == []
        assert summary_only['positions'] == [] and summary_only['orders'] == []
        assert summary_only['availability']['positions'] == 'unrecorded'
        assert compact['availability'] == {
            'summary': 'recorded', 'positions': 'unrecorded',
            'orders': 'unrecorded', 'trades': 'unrecorded'}
    finally:
        j.close()


def test_same_timestamp_uses_latest_sequence_and_no_future(tmp_path):
    j = journal(tmp_path)
    try:
        enable_account_evidence(j)
        first = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '1', 'roll_commission': '0',
            'actual_fill_count': 1, 'closed_trade_count': 0, 'open_position': 1})
        second = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '2', 'roll_commission': '0',
            'actual_fill_count': 2, 'closed_trade_count': 0, 'open_position': 1})
        second['summary']['balance'] = 100001
        save_account(j, first, trigger='bar_close')
        save_account(j, second, trigger='fill')

        assert read_account(j.db, at_ns=99) is None
        assert read_account(j.db, at_ns=100)['summary']['balance'] == 100001
        assert read_account(j.db)['time_ns'] == '100'
        window = account_window(j.db, first_ns=101, as_of_ns=200)
        assert window['seed']['time_ns'] == '100'
        assert window['samples'] == []
    finally:
        j.close()


def test_costs_reconciled_tolerance_and_separate_totals(tmp_path):
    assert costs_reconciled('10.00', '10.01')
    assert not costs_reconciled('10.00', '10.0101')
    j = journal(tmp_path)
    try:
        enable_account_evidence(j)
        snapshot = account_snapshot(Api(), time_ns=100, status='active', totals={
            'commission_total': '10', 'roll_commission': '4',
            'actual_fill_count': 2, 'closed_trade_count': 1, 'open_position': 0})
        assert snapshot['summary']['commission'] == 3
        assert snapshot['summary']['commission_total'] == '10'
        assert snapshot['summary']['roll_commission'] == '4'
    finally:
        j.close()


def test_fill_fees_are_atomic_and_repeated_keys_do_not_double_count(tmp_path):
    j = journal(tmp_path)
    fill = dict(key='t1', order_id='o1', symbol='SHFE.rb2505', direction='BUY',
                offset='OPEN', volume=1, price=3300, time_ns=100)
    key = research_trade_key(fill)
    fee = dict(fill_key=key, amount='2', role='strategy_open')
    try:
        enable_account_evidence(j)
        assert j.commit_update('event-1', time_ns=100, kind='fill', payload={},
            risk_state=RiskState(), fills=[fill], fill_fees=[fee])
        assert j.db.execute('SELECT amount FROM research_fill_fees').fetchall() == [('2',)]
        assert not j.commit_update('event-2', time_ns=101, kind='fill', payload={},
            risk_state=RiskState(), fills=[fill], fill_fees=[fee])
        assert j.db.execute('SELECT count(*) FROM research_fill_fees').fetchone()[0] == 1
    finally:
        j.close()

    j = journal(tmp_path / 'rollback')
    try:
        enable_account_evidence(j)
        j.db.execute("CREATE TRIGGER fail_fee BEFORE INSERT ON research_fill_fees "
                     "BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with pytest.raises(sqlite3.IntegrityError):
            j.commit_update('event-1', time_ns=100, kind='fill', payload={},
                risk_state=RiskState(), fills=[fill], fill_fees=[fee])
        assert j.db.execute('SELECT count(*) FROM fills').fetchone()[0] == 0
        assert j.db.execute('SELECT count(*) FROM risk_events').fetchone()[0] == 0
    finally:
        j.close()


def test_legacy_account_read_does_not_mutate_file(tmp_path):
    j = journal(tmp_path)
    try:
        path = j.path / 'journal.sqlite3'
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot = read_account(j.db)
        assert snapshot['status'] == 'legacy_partial'
        assert snapshot['availability']['orders'] == 'unrecorded'
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert after == before
    finally:
        j.close()


def test_incomplete_new_account_model_is_rejected(tmp_path):
    j = journal(tmp_path)
    try:
        enable_account_evidence(j)
        j.db.execute('DROP TABLE research_fill_fees')
        with pytest.raises(ValueError):
            read_account(j.db)
    finally:
        j.close()


def test_fixed_backtest_persists_account_and_fill_fees(tmp_path):
    raw = pivot_config_data()
    raw['end'] = raw['start']
    result = execute_research('backtest', validate_research_config(raw), tmp_path,
                              ('fixture', 'private-password'), sdk=sdk_for_pivot())
    assert result['status'] == 'backtest_finished', result
    with sqlite3.connect(tmp_path/result['run_id']/'journal.sqlite3') as db:
        snapshot = read_account(db)
        fills = db.execute('SELECT count(*) FROM fills').fetchone()[0]
        fees = db.execute('SELECT count(*) FROM research_fill_fees').fetchone()[0]
        assert fills > 0 and fees == fills
        assert snapshot['summary']['actual_fill_count'] == fills
        assert snapshot['summary']['balance'] is not None
        assert float(snapshot['summary']['commission_total']) > 0
        assert snapshot['status'] == 'last_snapshot'


def test_continuous_backtest_persists_account_and_fill_fees(tmp_path):
    fixture = ContinuousSdkFixture()
    result = execute_research('backtest', continuous_config(), tmp_path,
                              ('fixture', 'private-password'), sdk=fixture.sdk)
    assert result['status'] == 'backtest_finished', result
    with sqlite3.connect(tmp_path/result['run_id']/'journal.sqlite3') as db:
        snapshot = read_account(db)
        fills = db.execute('SELECT count(*) FROM fills').fetchone()[0]
        fees = db.execute('SELECT count(*) FROM research_fill_fees').fetchone()[0]
        assert fills > 0 and fees == fills
        assert snapshot['summary']['actual_fill_count'] == fills
        assert snapshot['summary']['closed_trade_count'] == result['summary']['closed_trade_count']
        assert snapshot['summary']['open_position'] == result['summary']['open_position']
        assert float(snapshot['summary']['commission_total']) > 0
