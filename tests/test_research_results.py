from dataclasses import replace
from decimal import Decimal

import pytest
from research_helpers import config_data
from test_research_journal import fill, journal
from test_trade_risk import entered

from qf.research_journal import ResearchJournal
from qf.research_results import compare_runs, read_run, summarize_run


def test_realized_trade_count_and_open_position_are_distinct(tmp_path):
    j = journal(tmp_path)
    j.set('initial_equity', 100000)
    for time_ns, balance in enumerate([100000, 110000, 99000], start=1):
        j.equity(time_ns, balance, 10)
    j.commit_update('open', time_ns=10, kind='fill', payload={}, risk_state=entered(),
                    fills=[fill()])
    j.commit_update('half', time_ns=11, kind='fill', payload={},
                    risk_state=replace(entered(), quantity=1),
                    fills=[fill(key='close-1', direction='SELL', offset='CLOSE', volume=1)])
    identity = j.path.name
    j.close()
    result = summarize_run(tmp_path, identity)
    assert result['max_drawdown_amount'] == '11000'
    assert result['max_drawdown_pct'] == '10'
    assert Decimal(result['net_pnl']) == -1000
    assert Decimal(result['gross_pnl']) == -990
    assert result['closed_trade_count'] == 0
    assert result['open_position'] == 1


def test_missing_old_schema_or_foreign_run_never_reads_live_market(tmp_path):
    for identity in ('../secret', 'C:/Windows', 'missing'):
        with pytest.raises(ValueError):
            read_run(tmp_path, identity)
    j = journal(tmp_path)
    j.set('research_schema', 99)
    identity = j.path.name
    j.close()
    with pytest.raises(ValueError):
        read_run(tmp_path, identity)


def test_compare_exposes_precision_and_cost_differences(tmp_path):
    j = journal(tmp_path)
    first = j.path.name
    j.close()
    data = config_data()
    data.update(precision='tick', fast_period=10, slow_period=30)
    j = ResearchJournal.create(tmp_path, 'backtest', data)
    j.set('fee_multiplier', 2)
    second = j.path.name
    j.close()
    comparison = compare_runs(tmp_path, [first, second])
    assert comparison['config_differences']['fast_period'] == [5, 10]
    assert comparison['comparability_warnings']


@pytest.mark.parametrize('corruption', ['positions', 'negative_fill'])
def test_corrupt_positions_or_fill_are_rejected(tmp_path, corruption):
    j = journal(tmp_path)
    if corruption == 'positions':
        j.set('final_positions', {'SHFE.rb2505': ['not-a-lot', 0]})
    else:
        j.fill(fill(volume=-1))
    identity = j.path.name
    j.close()
    with pytest.raises(ValueError):
        summarize_run(tmp_path, identity)
