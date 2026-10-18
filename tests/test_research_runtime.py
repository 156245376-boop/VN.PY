import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from research_helpers import config_data
from research_sdk import Api, sdk_for

from qf.research_config import validate_research_config
from qf.research_results import summarize_run
from qf.research_runtime import execute_research
from qf.runtime import provenance


def config():
    raw = config_data()
    raw.update(fast_period=2, slow_period=3, bar_seconds=60)
    return validate_research_config(raw)


def test_risk_runs_on_quote_without_new_bar(tmp_path):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for())
    assert result['status'] == 'backtest_finished'
    api = Api.instances[0]
    assert api.targets == [2, 0]
    assert api.positions['SHFE.rb2505'].pos_long == 0
    assert api.closed
    assert summarize_run(tmp_path, result['run_id'])['closed_trade_count'] == 1


def test_partial_entry_stop_cancels_then_reconciles_late_fill(tmp_path):
    cfg = config()
    cfg = replace(cfg, risk=replace(cfg.risk, risk_budget=Decimal(1500)))
    result = execute_research('backtest', cfg, tmp_path, ('u', 'p'), sdk=sdk_for('partial'))
    assert result['status'] == 'backtest_finished'
    api = Api.instances[0]
    assert api.targets == [3, 0]
    assert api.positions['SHFE.rb2505'].pos_long == 0
    assert sum(t.volume for t in api.trades.values() if t.offset == 'CLOSE') == 3


def test_reverse_waits_for_flat_and_no_orders(tmp_path):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for('reverse'))
    assert result['status'] == 'backtest_finished'
    assert Api.instances[0].targets == [2, 0, -2]
    trades = list(Api.instances[0].trades.values())
    assert [t.offset for t in trades] == ['OPEN', 'CLOSE', 'OPEN']


def test_tick_denied_does_not_change_precision_contract_or_account(tmp_path):
    result = execute_research('backtest', replace(config(), precision='tick'), tmp_path,
                              ('u', 'p'), sdk=sdk_for('tick_denied'))
    assert result['status'] == 'failed'
    assert Api.instances[0].subscriptions == [('tick', 'SHFE.rb2505')]
    assert 'private-secret' not in str(result)


def test_minute_subscription_exists_with_hourly_signal(tmp_path):
    cfg = replace(config(), bar_seconds=3600)
    execute_research('backtest', cfg, tmp_path, ('u', 'p'), sdk=sdk_for())
    assert set(Api.instances[0].subscriptions) == {('kline', 60), ('kline', 3600)}


@pytest.mark.parametrize('scenario,reason', [('reject', 'order_rejected'),
                                           ('disconnect', 'connection_lost'),
                                           ('foreign', 'external_order')])
def test_resume_missing_risk_external_order_disconnect_and_expiry_freeze(
        tmp_path, scenario, reason):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for(scenario))
    assert result['status'] == 'frozen'
    assert result['reason'] == reason
    assert Api.instances[0].closed


def test_resume_without_risk_snapshot_is_frozen_and_expired_paper_never_trades(tmp_path):
    sdk = sdk_for()
    first = execute_research('paper', config(), tmp_path, ('u', 'p'), sdk=sdk,
                             stop_requested=lambda: True)
    assert first['status'] == 'stopped'
    with sqlite3.connect(tmp_path/first['run_id']/'journal.sqlite3') as db:
        db.execute("DELETE FROM state WHERE key='risk_state'")
    resumed = execute_research('paper', config(), tmp_path, ('u', 'p'), sdk=sdk,
                               resume=first['run_id'], activate=True)
    assert resumed['status'] == 'frozen'
    assert resumed['reason'] == 'resume_incomplete'
    expired = execute_research('paper', config(), tmp_path, ('u', 'p'), sdk=sdk_for('expired'),
                               activate=True, stop_requested=lambda: True)
    assert expired['reason'] == 'contract_near_expiry'
    assert not Api.instances[0].targets


def test_close_unconfirmed_does_not_report_flat(tmp_path):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for('stuck'))
    assert result['status'] == 'frozen'
    assert result['reason'] == 'cancellation_unconfirmed'


def test_empty_backtest_never_claims_completed_or_zero_profit(tmp_path):
    result = execute_research('backtest', config(), tmp_path, ('u', 'p'), sdk=sdk_for('empty'))
    assert result['status'] == 'failed'
    assert result['summary']['net_pnl'] is None


def test_provenance_hash_includes_research_frontend(tmp_path):
    (tmp_path/'qf/web').mkdir(parents=True)
    for name in ('pyproject.toml', 'uv.lock'):
        (tmp_path/name).write_text('fixture')
    path = tmp_path/'qf/web/research.js'
    path.write_text('first')
    first = provenance(source_root=tmp_path)
    path.write_text('second')
    assert provenance(source_root=tmp_path)['source_sha256'] != first['source_sha256']
