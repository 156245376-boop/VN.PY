from pathlib import Path

import pytest
from research_helpers import config_data

from qf.config import load_config
from qf.research_config import validate_research_config


def test_new_config_does_not_change_legacy_period():
    assert load_config(Path("experiments/rb-demo.toml")).period == 15
    config = validate_research_config(config_data())
    assert config.bar_seconds == 300
    assert config.risk.risk_budget == 1000
    assert validate_research_config(config.public()) == config


@pytest.mark.parametrize("field,value", [("password", "secret"), ("bar_seconds", True),
    ("initial_balance", "NaN"), ("initial_balance", "Infinity"), ("fast_period", 20),
    ("symbol", "KQ.m@SHFE.rb"), ("symbol", "../secret"), ("end", "2025-01-01")])
def test_config_rejects_unknown_secret_bool_nan_and_invalid_stairs(field, value):
    raw = config_data()
    raw[field] = value
    with pytest.raises(ValueError):
        validate_research_config(raw)


@pytest.mark.parametrize("field,value", [("fixed_lots", True), ("stop_ticks", 0),
    ("second_lock_r", "2"), ("take_profit_value", "1.5"), ("max_margin_ratio", "1.1"),
    ("stairs_enabled", "yes"), ("token", "secret")])
def test_invalid_risk_fields_fail(field, value):
    raw = config_data()
    raw["risk"][field] = value
    with pytest.raises(ValueError):
        validate_research_config(raw)
