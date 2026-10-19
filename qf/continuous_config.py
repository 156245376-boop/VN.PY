"""历史主力连续实验；固定月份配置保持独立和向后兼容。"""

from dataclasses import dataclass

from qf.research_config import ResearchConfig, migrate_to_pivot, validate_research_config


@dataclass(frozen=True)
class ContinuousConfig(ResearchConfig):
    symbol: None
    contract_mode: str
    signal_adjustment: str
    roll_policy: str


def migrate_to_continuous(config: ResearchConfig, *, name: str) -> ContinuousConfig:
    source = migrate_to_pivot(config, name=name) if config.schema_version == 1 else config
    raw = source.public()
    raw.update(schema_version=3, strategy_version=3, symbol=None, name=name,
               contract_mode='historical_main', signal_adjustment='causal_forward_gap_v1',
               roll_policy='close_then_reopen_preserve_r_v1')
    return validate_research_config(raw)
