import pytest
from research_helpers import config_data, pivot_config_data

from qf import research_config as rc
from qf.experiment_store import ExperimentStore


def test_v2_optional_caps_roundtrip(tmp_path):
    store = ExperimentStore(tmp_path)
    cfg = rc.validate_research_config(pivot_config_data())
    ref = store.save(cfg)
    loaded = store.load(ref['experiment_id'], 1)
    assert loaded.schema_version == loaded.strategy_version == 2
    assert loaded.risk.max_lots is None and loaded.risk.max_margin_ratio is None
    assert loaded.risk.pivot_left == loaded.risk.pivot_right == 2
    assert loaded.public() == cfg.public()


@pytest.mark.parametrize('field', ['max_lots', 'max_margin_ratio'])
def test_enabled_cap_requires_value_and_locates_field(field):
    raw = pivot_config_data()
    raw['risk']['limit_lots' if field == 'max_lots' else 'limit_margin'] = True
    with pytest.raises(rc.ResearchValidationError) as error:
        rc.validate_research_config(raw)
    assert 'risk.' + field in error.value.field_errors


@pytest.mark.parametrize('field,value', [
    ('pivot_left', True), ('pivot_right', 0), ('pivot_right', 51),
    ('risk_budget', 'NaN'), ('limit_margin', 1), ('token', 'private-secret'),
    ('stop_ticks', 10), ('stop_method', 'guessed'),
])
def test_v2_rejects_unsafe_and_mixed_risk(field, value):
    raw = pivot_config_data()
    raw['risk'][field] = value
    with pytest.raises(rc.ResearchValidationError) as error:
        rc.validate_research_config(raw)
    assert 'private-secret' not in str(error.value)


def test_mixed_version_and_fixed_lots_above_enabled_cap():
    raw = pivot_config_data()
    raw['strategy_version'] = 1
    with pytest.raises(rc.ResearchValidationError):
        rc.validate_research_config(raw)
    raw = pivot_config_data()
    raw['risk'].update(sizing='fixed', fixed_lots=3, limit_lots=True, max_lots=2)
    with pytest.raises(rc.ResearchValidationError) as error:
        rc.validate_research_config(raw)
    assert 'risk.fixed_lots' in error.value.field_errors


def test_legacy_copy_upgrade_preserves_original_bytes(tmp_path):
    store = ExperimentStore(tmp_path)
    original = store.save(rc.validate_research_config(config_data()))
    path = tmp_path / original['experiment_id'] / '1.toml'
    before = path.read_bytes()
    copy = store.copy(original['experiment_id'], 1, name='拐点副本', upgrade_to_pivot=True)
    cfg = store.load(copy['experiment_id'], 1)
    assert path.read_bytes() == before
    assert copy['experiment_id'] != original['experiment_id']
    assert copy['parent'] == {'experiment_id': original['experiment_id'], 'revision': 1}
    assert cfg.schema_version == cfg.strategy_version == 2
    assert cfg.risk.limit_lots and cfg.risk.max_lots == 10
    assert cfg.risk.limit_margin and cfg.risk.max_margin_ratio == pytest.approx(0.5)
    assert cfg.risk.pivot_left == cfg.risk.pivot_right == 2


def test_query_validation_does_not_require_trading_parameters():
    result = rc.validate_contract_request('KQ.m@CZCE.FG', '2016-01-03', '2026-10-07')
    assert result == dict(continuous='KQ.m@CZCE.FG', start='2016-01-03', end='2026-10-07')
    with pytest.raises(rc.ResearchValidationError) as error:
        rc.validate_contract_request('KQ.m@CZCE.FG', '2026-10-07', '2016-01-03')
    assert 'end' in error.value.field_errors
