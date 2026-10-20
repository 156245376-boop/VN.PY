import json
from urllib.request import urlopen

import pytest
from research_helpers import config_data
from test_local_dataset_builder import (
    build_local_dataset_from_validation,
    write_validation,
)

from qf.local_runtime import execute_local_research
from qf.replay_view import ReplayView
from qf.research_journal import ResearchJournal


def saved_run(root):
    j = ResearchJournal.create(root, 'backtest', config_data())
    j.capture_bars('SHFE.rb2505', 300, [dict(datetime=1740963600000000000+i*300000000000,
        open=100+i, high=102+i, low=99+i, close=101+i, volume=10, close_oi=20)
        for i in range(40)])
    j.set('status', 'backtest_finished')
    identity = j.path.name
    j.checkpoint_integrity()
    j.close()
    return identity


def test_replay_opens_without_sdk_or_credentials(tmp_path, monkeypatch):
    identity = saved_run(tmp_path)
    monkeypatch.setattr('tqsdk.TqApi', lambda *a, **k: pytest.fail('不能创建账户会话'))
    view = ReplayView(tmp_path)
    try:
        url = view.open(identity)
        assert url.startswith('http://127.0.0.1:')
        html = urlopen(url).read().decode()
        assert '离线复盘' in html
        payload = json.loads(urlopen(url+'replay').read())
        assert payload['run_id'] == identity
        assert len(payload['ma_series']) == 2
        page = json.loads(urlopen(url+'bars?offset=0&limit=20').read())
        assert len(page['bars']) == 20
        assert page['total_bars'] == 40
    finally:
        view.close()


def test_replay_rejects_path_traversal_old_schema_and_missing_bars(tmp_path):
    view = ReplayView(tmp_path)
    for identity in ('../secret', 'missing'):
        with pytest.raises(ValueError):
            view.open(identity)
    j = ResearchJournal.create(tmp_path, 'backtest', config_data())
    j.set('status', 'backtest_finished')
    identity = j.path.name
    j.close()
    with pytest.raises(ValueError):
        view.open(identity)
    view.close()


def test_local_replay_reads_normalized_dataset_without_sdk(tmp_path, monkeypatch):
    config, validation_id = write_validation(tmp_path)
    dataset_id, _dataset = build_local_dataset_from_validation(
        tmp_path, validation_id, config
    )
    run = execute_local_research(
        config,
        tmp_path,
        dataset_id,
        stop_requested=lambda: False,
    )
    monkeypatch.setattr('tqsdk.TqApi', lambda *a, **k: pytest.fail('不能创建账户会话'))
    view = ReplayView(tmp_path)
    try:
        url = view.open(run['run_id'])
        payload = json.loads(urlopen(url+'replay').read())
        assert payload['engine_kind'] == 'local_research'
        assert payload['actual_symbols'] == ['SHFE.rb2505']
        assert payload['ma_series']
        page = json.loads(urlopen(url+'bars?offset=0&limit=20').read())
        assert page['total_bars'] == 1
        assert page['bars'][0]['close'] == 280
    finally:
        view.close()
