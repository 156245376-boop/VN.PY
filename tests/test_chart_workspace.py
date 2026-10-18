import copy
import json

import pytest

from qf.chart_workspace import ChartWorkspaceStore, default_workspace, validate_workspace


def test_defaults_and_strict_validation():
    config = default_workspace()
    assert config['layout'] == 'single' and config['linked'] is False
    assert [p['id'] for p in config['panes']] == [f'pane-{i}' for i in range(1, 5)]
    assert validate_workspace(config) == config
    for patch in ({'layout': 'six'}, {'split': {'column': True, 'row': .5}},
                  {'split': {'column': float('nan'), 'row': .5}}, {'password': 'secret'}):
        with pytest.raises(ValueError):
            validate_workspace(config | patch)
    bad = copy.deepcopy(config)
    bad['panes'][1]['id'] = 'pane-1'
    with pytest.raises(ValueError):
        validate_workspace(bad)


def test_store_restore_and_corruption_are_explicit(tmp_path):
    store = ChartWorkspaceStore(tmp_path)
    config = store.load()['workspace']
    config['panes'][0]['continuous'] = 'KQ.m@SHFE.rb'
    config['panes'][0]['period'] = '1h'
    store.save(config)
    assert store.load()['workspace'] == config
    raw = json.loads(store.path.read_text('utf-8'))
    assert 'chart_url' not in raw
    store.path.write_text('{broken', encoding='utf-8')
    assert store.load()['issue']
    with pytest.raises(ValueError):
        store.save(default_workspace())
    assert store.path.read_text('utf-8') == '{broken'


def test_atomic_failure_preserves_old_file(tmp_path, monkeypatch):
    store = ChartWorkspaceStore(tmp_path)
    store.save(default_workspace())
    before = store.path.read_bytes()
    monkeypatch.setattr('qf.chart_workspace.os.replace', lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        store.save(default_workspace() | {'layout': 'quad'})
    assert store.path.read_bytes() == before
