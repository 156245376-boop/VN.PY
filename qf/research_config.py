"""新研究实验的严格公开配置；与旧固定样例的Config隔离。"""

import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


def decimal_value(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("数值格式无效")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("数值格式无效") from None
    if not result.is_finite():
        raise ValueError("数值必须有限")
    return result


def public_values(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: public_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_values(v) for v in value]
    return value


@dataclass(frozen=True)
class RiskConfig:
    sizing: str
    fixed_lots: int
    risk_budget: Decimal
    stop_ticks: int
    max_lots: int
    max_margin_ratio: Decimal
    take_profit_mode: str
    take_profit_value: Decimal
    stairs_enabled: bool
    first_trigger_r: Decimal
    first_offset_ticks: int
    second_trigger_r: Decimal
    second_lock_r: Decimal


@dataclass(frozen=True)
class ResearchConfig:
    schema_version: int
    strategy_id: str
    strategy_version: int
    name: str
    symbol: str
    continuous: str
    bar_seconds: int
    fast_period: int
    slow_period: int
    start: date
    end: date
    initial_balance: Decimal
    precision: str
    timeout_seconds: int
    execution_timeout_seconds: int
    risk: RiskConfig

    def public(self):
        return public_values(asdict(self))


def _integer(value, low, high=None):
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError("整数不在允许范围内")
    return value


def validate_research_config(raw: dict) -> ResearchConfig:
    if not isinstance(raw, dict) or set(raw) != set(ResearchConfig.__annotations__):
        raise ValueError("实验配置字段不完整或包含未知字段")
    data = dict(raw)
    risk = data.pop('risk')
    if not isinstance(risk, dict) or set(risk) != set(RiskConfig.__annotations__):
        raise ValueError("风险配置字段不完整或包含未知字段")
    risk = dict(risk)
    if (_integer(data['schema_version'], 1, 1) != 1 or data['strategy_id'] != 'ma_cross'
            or _integer(data['strategy_version'], 1, 1) != 1):
        raise ValueError("不支持的策略或配置版本")
    if (not isinstance(data['name'], str) or not data['name'].strip()
            or len(data['name']) > 80 or any(ord(c) < 32 for c in data['name'])):
        raise ValueError("请填写不超过80字的实验名称")
    symbol = data['symbol']
    match = (re.fullmatch(r'(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.([A-Za-z]+)\d{3,4}', symbol)
             if isinstance(symbol, str) else None)
    if not match or data['continuous'] != f'KQ.m@{match[1]}.{match[2]}':
        raise ValueError("实际合约与品种不匹配")
    if _integer(data['bar_seconds'], 1) not in (60, 300, 900, 1800, 3600, 86400):
        raise ValueError("不支持的K线周期")
    for key in ('fast_period', 'slow_period'):
        _integer(data[key], 2, 200)
    if data['fast_period'] >= data['slow_period']:
        raise ValueError("快均线周期必须小于慢均线")
    for key in ('start', 'end'):
        if not isinstance(data[key], str):
            raise ValueError("日期格式无效")
        try:
            data[key] = date.fromisoformat(data[key])
        except ValueError:
            raise ValueError("日期格式无效") from None
    if data['start'] > data['end']:
        raise ValueError("起始日期不能晚于结束日期")
    if data['precision'] not in ('minute', 'tick'):
        raise ValueError("不支持的回测精度")
    for key in ('timeout_seconds', 'execution_timeout_seconds'):
        _integer(data[key], 5, 600)
    data['initial_balance'] = decimal_value(data['initial_balance'])
    if data['initial_balance'] <= 0:
        raise ValueError("初始虚拟资金必须大于零")
    for key in ('fixed_lots', 'stop_ticks', 'max_lots', 'first_offset_ticks'):
        _integer(risk[key], 1)
    for key in ('risk_budget', 'max_margin_ratio', 'take_profit_value',
                'first_trigger_r', 'second_trigger_r', 'second_lock_r'):
        risk[key] = decimal_value(risk[key])
        if risk[key] <= 0:
            raise ValueError("风险参数必须大于零")
    if (risk['sizing'] not in ('fixed', 'risk_budget')
            or risk['take_profit_mode'] not in ('r_multiple', 'amount')
            or type(risk['stairs_enabled']) is not bool or risk['max_margin_ratio'] > 1):
        raise ValueError("仓位或退出参数无效")
    if risk['sizing'] == 'fixed' and risk['fixed_lots'] > risk['max_lots']:
        raise ValueError("固定手数超过最大手数")
    if risk['stairs_enabled'] and (
            risk['second_trigger_r'] <= risk['first_trigger_r']
            or risk['second_lock_r'] >= risk['second_trigger_r']
            or (risk['take_profit_mode'] == 'r_multiple'
                and risk['take_profit_value'] <= risk['second_trigger_r'])):
        raise ValueError("阶梯顺序或终点无效：后续阶梯必须能够到达")
    return ResearchConfig(**data, risk=RiskConfig(**risk))
