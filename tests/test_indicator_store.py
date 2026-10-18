import copy

import pytest

from qf.indicator_catalog import default_item
from qf.indicator_store import IndicatorStore, default_indicators, validate_indicator_config


def test_defaults_and_roundtrip(tmp_path):
    store = IndicatorStore(tmp_path)
    config = store.load()['config']
    assert list(config['panes']) == [f'pane-{i}' for i in range(1, 5)]
    assert [i['type'] for i in config['panes']['pane-1']['items']] == ['volume', 'oi']
    store.save(config)
    assert store.load()['config'] == config


def test_bad_file_is_preserved(tmp_path):
    store = IndicatorStore(tmp_path)
    store.path.write_text('{broken', encoding='utf-8')
    assert store.load()['issue']
    with pytest.raises(ValueError):
        store.save(default_indicators())
    assert store.path.read_text('utf-8') == '{broken'


def test_atomic_failure_keeps_old_file(tmp_path, monkeypatch):
    store = IndicatorStore(tmp_path)
    store.save(default_indicators())
    original = store.path.read_bytes()
    monkeypatch.setattr('qf.indicator_store.os.replace',
                        lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        store.save(default_indicators())
    assert store.path.read_bytes() == original


def test_ns_strings_roundtrip_without_precision_loss(tmp_path):
    config = default_indicators()
    item = default_item('vp', 'vp-fixed')
    item['params'].update(mode='fixed', range={'symbol': 'SHFE.rb2701',
        'start_ns': '1700000000000000001', 'end_ns': '1700000000000000002'})
    config['panes']['pane-1']['items'].append(item)
    store = IndicatorStore(tmp_path)
    store.save(config)
    assert store.load()['config'] == config
    for bad in (config | {'token': 'private'}, config | {'schema': True}):
        with pytest.raises(ValueError):
            validate_indicator_config(bad)
    duplicate = copy.deepcopy(config)
    duplicate['panes']['pane-1']['items'].append(item)
    with pytest.raises(ValueError):
        validate_indicator_config(duplicate)
