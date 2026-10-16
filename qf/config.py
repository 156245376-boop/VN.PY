import math
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Config:
    symbol: str
    continuous: str
    start: date
    end: date
    initial_balance: float
    period: int
    lots: int
    timeout_seconds: int
    execution_timeout_seconds: int

    def public(self):
        values = asdict(self)
        values.update(start=str(self.start), end=str(self.end))
        return values


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(data) != set(Config.__annotations__):
        raise ValueError("配置字段不完整或包含不允许的字段（配置禁止保存凭证）")
    config = Config(**data)
    if (config.symbol != "SHFE.rb2505" or config.continuous != "KQ.m@SHFE.rb"
            or config.start != date(2025, 3, 3) or config.end != date(2025, 3, 7)
            or config.initial_balance != 100000 or config.lots != 1
            or type(config.period) is not int or config.period < 2 or config.period > 200
            or any(type(v) is not int or not 5 <= v <= 600 for v in
                   (config.timeout_seconds, config.execution_timeout_seconds))
            or not math.isfinite(config.initial_balance)):
        raise ValueError("首轮样本、资金、手数固定；周期与超时须在允许范围内")
    return config
