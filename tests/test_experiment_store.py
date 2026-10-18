import os

import pytest
from research_helpers import config_data

from qf.experiment_store import ExperimentStore
from qf.research_config import validate_research_config


def test_copy_is_new_identity_and_revision_is_immutable(tmp_path):
    store = ExperimentStore(tmp_path)
    first = store.save(validate_research_config(config_data()))
    copied = store.copy(first['experiment_id'], first['revision'], name='比较B')
    assert copied['experiment_id'] != first['experiment_id']
    assert copied['parent'] == {k: first[k] for k in ('experiment_id', 'revision')}
    changed = config_data()
    changed.update(name='比较B', fast_period=10, slow_period=30)
    second = store.save(validate_research_config(changed), experiment_id=copied['experiment_id'])
    assert second['revision'] == 2
    assert store.load(first['experiment_id'], 1).fast_period == 5
    assert store.load(copied['experiment_id'], 2).fast_period == 10
    assert len(store.list()) == 2
    assert list(tmp_path.rglob('*.toml'))


def test_store_rejects_traversal_and_interrupted_write_preserves_previous(tmp_path, monkeypatch):
    store = ExperimentStore(tmp_path)
    first = store.save(validate_research_config(config_data()))
    for invalid in ('../secret', 'C:/Windows', '', 'a'*31):
        with pytest.raises(ValueError):
            store.load(invalid, 1)
    def denied(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr(os, 'replace', denied)
    with pytest.raises(OSError):
        store.save(validate_research_config(config_data()), experiment_id=first['experiment_id'])
    assert store.load(first['experiment_id'], 1).fast_period == 5
    assert len(store.list()) == 1
