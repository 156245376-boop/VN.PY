import json
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from test_continuous_journal import arguments, journal, rolling, seed, state
from test_continuous_risk import spec
from test_continuous_series import BASE, MINUTE

from qf.continuous_results import ContinuousReader, continuous_snapshot, summarize_continuous_run
from qf.research_config import validate_research_config
from qf.research_results import read_run, summarize_run


def finished(root):
    j = journal(root)
    seed(j)
    j.record_spec('SHFE.rb2510', replace(spec(), symbol='SHFE.rb2510'))
    risk = state()
    for i, (symbol, direction, offset, price, role, quantity, realized) in enumerate([
        ('SHFE.rb2505', 'SELL', 'CLOSE', 280, 'roll_out', 0, 1800),
        ('SHFE.rb2510', 'BUY', 'OPEN', 380, 'roll_in', 1, 1800),
        ('SHFE.rb2510', 'SELL', 'CLOSE', 400, 'strategy_close', 0, 2000)], 1):
        args = arguments()
        f = dict(args['fills'][0], key=f'fill{i}', symbol=symbol, direction=direction,
                 offset=offset, price=price, time_ns=BASE+i*MINUTE)
        risk = replace(risk, quantity=quantity, realized_gross=D(realized),
                       entry_price=D(price) if role == 'roll_in' else risk.entry_price)
        j.commit_continuous(f'e{i}', time_ns=f['time_ns'], kind='fill',
            payload={'role': role, 'symbol': symbol}, logical_risk=risk,
            roll_state=rolling(), fills=[f])
    j.set('initial_equity', '100000')
    j.set('sdk_statistics', {'end_balance': '101992', 'commission': '8'})
    j.set('total_commission', '8')
    j.set('status', 'backtest_finished')
    j.set('final_positions', {})
    j.export()
    return j


def test_roll_out_is_not_logical_exit_and_sdk_net_keeps_all_costs(tmp_path):
    j = finished(tmp_path)
    try:
        s = summarize_continuous_run(tmp_path, j.path.name)
        assert s['closed_trade_count'] == 1
        assert D(s['net_pnl']) == D('101992')-D('100000')
        assert D(s['roll_commission']) == D(4)
        assert s['fill_count'] == 4
        assert summarize_run(tmp_path, j.path.name) == s
        assert read_run(tmp_path, j.path.name)['coverage']['bars'] == 1
    finally:
        j.close()


@pytest.mark.parametrize('table,column', [('main_changes', 'data'),
    ('signal_bars', 'data'), ('logical_fills', 'symbol')])
def test_tampered_continuous_result_is_rejected(tmp_path, table, column):
    j = finished(tmp_path)
    try:
        with j.db:
            j.db.execute(f'UPDATE {table} SET {column}=?', ('corrupt',))
        with pytest.raises(ValueError):
            read_run(tmp_path, j.path.name)
    finally:
        j.close()


def test_series_filter_ids_and_actual_fill_price_are_explicit(tmp_path):
    j = finished(tmp_path)
    try:
        reader = ContinuousReader(j.path)
        signal = reader.bars(0, 2000)
        assert len(signal['bars']) == 1 and signal['bars'][0]['global_id'] == 0
        assert signal['bars'][0]['source_symbol'] == 'SHFE.rb2505'
        actual = reader.bars(0, 10, series='actual', symbol='SHFE.rb2510')
        assert len(actual['bars']) == 1 and float(actual['bars'][0]['close']) == 200
        with pytest.raises(ValueError):
            reader.bars(0, 10, series='actual')
        with pytest.raises(ValueError):
            reader.bars(0, 10, series='actual', symbol='SHFE.cu2505')
        config = validate_research_config(j.get('config'))
        snap = continuous_snapshot(j, config, SimpleNamespace(), now=BASE+MINUTE,
                                    revision=1, progress={})
        assert snap['symbol'] == config.continuous
        assert snap['fills'][0]['price'] == 280
        assert D(snap['fills'][0]['display_price']) == 280
        assert snap['main_changes'][0]['new_symbol'] == 'SHFE.rb2505'
        assert reader.locate(str(BASE), series='signal')['global_id'] == 0
    finally:
        j.close()


def test_million_bar_initial_page_and_live_snapshot_stay_bounded(tmp_path):
    j = journal(tmp_path)
    try:
        seed(j)
        # SQLite 合成大样本；不在 Python 或浏览器里构造百万对象。
        data = j.db.execute('SELECT data FROM signal_bars').fetchone()[0]
        with j.db:
            j.db.execute('DELETE FROM signal_bars')
            j.db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 '
                'FROM n WHERE x<1199999) INSERT INTO signal_bars '
                'SELECT x,?+x*?,?+(x+1)*?, ?, '
                "json_set(?, '$.time_ns',cast(?+x*? AS TEXT), '$.datetime',?+x*?) FROM n",
                (BASE, MINUTE, BASE, MINUTE, 'SHFE.rb2505', data,
                 BASE, MINUTE, BASE, MINUTE))
        j.set('signal_count', 1200000)
        reader = ContinuousReader(j.path)
        page = reader.initial()
        assert len(page['bars']) == 2000 and page['offset'] == 1198000
        assert page['bars'][-1]['global_id'] == 1199999
        assert reader.locate(str(BASE+500000*MINUTE), series='signal')['global_id'] == 500000
        with pytest.raises(ValueError):
            reader.bars(0, 10001)
        snap = continuous_snapshot(j, validate_research_config(j.get('config')),
            SimpleNamespace(), now=BASE+1200001*MINUTE, revision=2, progress={})
        assert len(snap['bars']) == 500 and len(snap['risk_events']) <= 5000
        assert len(json.dumps(snap)) < 700000
    finally:
        j.close()
