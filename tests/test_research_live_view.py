import copy
import json
from importlib import import_module
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest


def service(provider):
    return import_module('qf.research_live_view').LiveResearchView(provider)


def frame(revision=1):
    return dict(run_id='20261019T000000-123456abcdef', revision=revision,
        symbol='SHFE.rb2505', bar_seconds=300, bars=[], fills=[], risk_events=[],
        ma_series=[], config={}, contract_spec={}, quote={}, as_of_ns='1740963900000000000',
        progress=dict(stage='backtesting', percent=50), terminal=False)


def test_live_view_never_constructs_sdk_or_exposes_auth(monkeypatch):
    monkeypatch.setattr('tqsdk.TqApi', lambda *a, **k: pytest.fail('不得连接账户'))
    current = [None]
    view = service(lambda: copy.deepcopy(current[0]))
    try:
        url = view.open()
        assert view.open() == url
        html = urlopen(url).read().decode()
        assert '__qfLiveResearch' in html and '__qfReplay=true' not in html
        pending = json.loads(urlopen(url+'snapshot?after_revision=0').read())
        assert pending['waiting']
        current[0] = frame()
        assert view.open() == url
        data = json.loads(urlopen(url+'snapshot?after_revision=0').read())
        assert data['changed'] and data['snapshot']['run_id'] == current[0]['run_id']
        assert 'private-password' not in html+json.dumps(data)
        for route in ('replay', 'orders', 'trade'):
            with pytest.raises(HTTPError):
                urlopen(url+route)
    finally:
        view.close()


def test_live_snapshot_identity_revision_and_source_are_checked():
    current = [frame()]
    view = service(lambda: copy.deepcopy(current[0]))
    try:
        url = view.open()
        assert json.loads(urlopen(url+'snapshot?after_revision=1').read())['changed'] is False
        current[0] = frame(2)
        data = json.loads(urlopen(url+'snapshot?after_revision=1').read())
        assert data['snapshot']['revision'] == 2 and data['generation'] == view.generation
        current[0]['run_id'] = '20261019T000001-123456abcdef'
        with pytest.raises(HTTPError) as error:
            urlopen(url+'snapshot?after_revision=1')
        assert error.value.code == 409
    finally:
        view.close()


def test_chart_consumes_only_processed_prefix(tmp_path):
    from types import SimpleNamespace

    from research_helpers import pivot_config_data

    from qf.research_config import validate_research_config
    from qf.research_journal import ResearchJournal
    from qf.research_snapshot import view_snapshot
    config = validate_research_config(pivot_config_data())
    journal = ResearchJournal.create(tmp_path, 'backtest', config.public())
    start = 1740963600000000000
    rows = [dict(datetime=start+i*300_000_000_000, open=100+i, high=102+i,
                 low=99+i, close=101+i, volume=10, close_oi=20) for i in range(600)]
    journal.capture_bars(config.symbol, config.bar_seconds, rows)
    try:
        snapshot = view_snapshot(journal, config, SimpleNamespace(),
            now=start+600*300_000_000_000, revision=1, progress={}, terminal=False)
        assert len(snapshot['bars']) == 500 and snapshot['first_bar_id'] == 100
        assert all(len(line['points']) == 500 for line in snapshot['ma_series'])
        assert snapshot['ma_series'][0]['points'][0]['id'] == 100
        assert journal.db.execute('SELECT count(*) FROM research_bars').fetchone()[0] == 600
        assert snapshot['bars'][0]['close'] == 201
        snapshot['bars'][0]['close'] = -1
        fresh = view_snapshot(journal, config, SimpleNamespace(),
            now=start+600*300_000_000_000, revision=2, progress={}, terminal=False)
        assert fresh['bars'][0]['close'] == 201
    finally:
        journal.close()
