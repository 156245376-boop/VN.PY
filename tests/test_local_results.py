import json
import sqlite3

import pytest
from test_local_backtest import config, dataset

from qf.backtest_parity import evidence_for_run
from qf.local_backtest import LocalBacktestEngine
from qf.local_results import save_local_result
from qf.research_results import compare_runs, read_run, summarize_run
from qf.trade_ledger import trade_ledger
from qf.workbench import WorkbenchBridge


def source_fingerprint():
    return {
        'code_version': 'fixture-code',
        'engine_version': 'local_research_v1',
        'dataset_sha256': 'fixture-data',
        'cost_source': 'fixture',
    }


def result():
    return LocalBacktestEngine().run(
        dataset(), config(), progress=None, cancel=lambda: False
    )


def test_local_result_keeps_engine_identity_and_trade_fees(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    summary = summarize_run(tmp_path, run_id)
    assert summary['engine_kind'] == 'local_research'
    assert summary['compute_backend'] == 'cpu'
    assert summary['cost_reconciled'] is True
    assert summary['trade_ledger']['fee_total'] == summary['commission']
    assert summary['trade_ledger']['reconciled'] is True
    assert summary['closed_trade_count'] == 1
    assert summary['net_pnl'] == '-1184'
    assert summary['gross_pnl'] == '-1120'
    assert summary['commission'] == '64'
    assert read_run(tmp_path, run_id)['engine_kind'] == 'local_research'
    assert (tmp_path/run_id/'trades.csv').is_file()
    assert (tmp_path/run_id/'equity.csv').is_file()
    assert (tmp_path/run_id/'summary.json').is_file()


def test_local_trade_ledger_exposes_stop_reason_and_fill_fees(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    with sqlite3.connect(tmp_path/run_id/'journal.sqlite3') as db:
        ledger = trade_ledger(db)
    assert ledger['available'] is True
    assert ledger['reconciled'] is True
    assert ledger['fee_total'] == '64'
    trade = ledger['trades'][0]
    assert trade['direction'] == 1
    assert trade['initial_stop'] == '97'
    assert trade['final_stop'] == '97'
    assert trade['exit_reason'] == 'initial_stop'
    assert trade['gross_pnl'] == '-1120'
    assert trade['fee'] == '64'
    assert trade['net_pnl'] == '-1184'
    assert {fill['fee'] for fill in trade['fills']} == {'32'}


def test_local_result_detects_tampered_query_table(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    with sqlite3.connect(tmp_path/run_id/'journal.sqlite3') as db:
        db.execute(
            "UPDATE fills SET fee='0' WHERE key='local-fill-0'"
        )
    with pytest.raises(ValueError, match='完整性'):
        summarize_run(tmp_path, run_id)


def test_local_result_rejects_credential_like_source_metadata(tmp_path):
    metadata = source_fingerprint() | {'password': 'must-not-save'}
    with pytest.raises(ValueError, match='凭证'):
        save_local_result(tmp_path, result(), metadata)
    assert list(tmp_path.iterdir()) == []


def test_saved_summary_is_utf8_json_without_credentials(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    raw = (tmp_path/run_id/'summary.json').read_text(encoding='utf-8')
    summary = json.loads(raw)
    assert summary['engine_kind'] == 'local_research'
    assert 'password' not in raw.lower()


def test_local_runs_can_be_compared_without_losing_engine_identity(tmp_path):
    first = save_local_result(tmp_path, result(), source_fingerprint())
    second = save_local_result(
        tmp_path,
        result(),
        source_fingerprint() | {'dataset_sha256': 'fixture-data-2'},
    )
    comparison = compare_runs(tmp_path, [first, second])
    assert [item['engine_kind'] for item in comparison['items']] == [
        'local_research',
        'local_research',
    ]
    assert comparison['items'][0]['source_fingerprint']['dataset_sha256'] != (
        comparison['items'][1]['source_fingerprint']['dataset_sha256']
    )


def test_workbench_reads_local_fill_and_trade_evidence(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    bridge = WorkbenchBridge.__new__(WorkbenchBridge)
    bridge._results_root = tmp_path
    details = bridge.get_research_result(run_id)
    assert details['ok'] is True
    fill = details['details']['fills'][0]
    packet = bridge.get_research_fill(run_id, fill['key'])
    assert packet['ok'] is True
    assert packet['details']['trade']['trade_id'] == fill['trade_id']
    trade = bridge.get_research_trade(run_id, fill['key'])
    assert trade['ok'] is True
    assert trade['details']['initial_r'] == '960'


def test_parity_evidence_reads_full_saved_local_result(tmp_path):
    run_id = save_local_result(tmp_path, result(), source_fingerprint())
    evidence = evidence_for_run(tmp_path, run_id)
    assert evidence['engine_kind'] == 'local_research'
    assert len(evidence['signals']) == 2
    assert len(evidence['fills']) == 2
    assert evidence['fees'] == '64'
