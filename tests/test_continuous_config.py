import copy

import pytest
from research_helpers import config_data, pivot_config_data

from qf.experiment_store import ExperimentStore
from qf.research_config import validate_research_config


def continuous_data():
    raw = pivot_config_data()
    raw.update(schema_version=3, strategy_version=3, symbol=None,
               contract_mode='historical_main', signal_adjustment='causal_forward_gap_v1',
               roll_policy='close_then_reopen_preserve_r_v1',
               start='2023-01-03', end='2025-12-31')
    return raw


@pytest.mark.parametrize('omit_symbol', [False, True])
def test_v3_without_month_roundtrips_toml(tmp_path, omit_symbol):
    raw = continuous_data()
    if omit_symbol:
        raw.pop('symbol')
    original = validate_research_config(raw)
    store = ExperimentStore(tmp_path)
    ref = store.save(original)
    loaded = store.load(ref['experiment_id'], ref['revision'])
    assert loaded.symbol is None
    assert loaded.public() == original.public()
    assert str(loaded.start) == '2023-01-03' and str(loaded.end) == '2025-12-31'
    assert loaded.schema_version == loaded.strategy_version == 3
    assert 'None' not in (tmp_path/ref['experiment_id']/'1.toml').read_text('utf-8')


@pytest.mark.parametrize('key,value', [('symbol', 'SHFE.rb2505'),
    ('contract_mode', 'fixed'), ('signal_adjustment', 'future_back_adjust'),
    ('roll_policy', 'reset_r'), ('strategy_version', 2), ('extra', True)])
def test_v3_rejects_wrong_mode_or_unknown_policy(key, value):
    raw = continuous_data()
    raw[key] = value
    with pytest.raises(ValueError):
        validate_research_config(raw)


@pytest.mark.parametrize('key', ['continuous', 'end', 'risk', 'roll_policy'])
def test_v3_only_symbol_can_be_omitted(key):
    raw = continuous_data()
    del raw[key]
    with pytest.raises(ValueError):
        validate_research_config(raw)


@pytest.mark.parametrize('factory', [config_data, pivot_config_data])
def test_upgrade_creates_new_identity_and_preserves_legacy(tmp_path, factory):
    raw = factory()
    before = copy.deepcopy(raw)
    store = ExperimentStore(tmp_path)
    old = store.save(validate_research_config(raw))
    path = tmp_path/old['experiment_id']/'1.toml'
    before_bytes = path.read_bytes()
    new = store.copy(old['experiment_id'], 1, name='连续副本', upgrade_to_continuous=True)
    cfg = store.load(new['experiment_id'], 1)
    assert new['experiment_id'] != old['experiment_id']
    assert new['parent'] == dict(experiment_id=old['experiment_id'], revision=1)
    assert path.read_bytes() == before_bytes and raw == before
    assert cfg.schema_version == 3 and cfg.symbol is None
    assert cfg.risk.risk_budget == 1000
    assert cfg.risk.limit_lots is (raw['schema_version'] == 1)
    assert store.load(old['experiment_id'], 1).schema_version == raw['schema_version']


def test_upgrade_flags_cannot_be_combined(tmp_path):
    store = ExperimentStore(tmp_path)
    old = store.save(validate_research_config(config_data()))
    with pytest.raises(ValueError):
        store.copy(old['experiment_id'], 1, name='无效',
                   upgrade_to_pivot=True, upgrade_to_continuous=True)
    assert len(store.list()) == 1


def test_missing_symbol_remains_invalid_for_v2():
    raw = pivot_config_data()
    raw.pop('symbol')
    with pytest.raises(ValueError):
        validate_research_config(raw)
