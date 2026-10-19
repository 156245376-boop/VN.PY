"""新研究实验的严格公开配置；与旧固定样例的Config隔离。"""

import re
from dataclasses import asdict, dataclass, fields
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
class PivotRiskConfig:
    sizing: str
    fixed_lots: int
    risk_budget: Decimal
    max_lots: int | None
    max_margin_ratio: Decimal | None
    take_profit_mode: str
    take_profit_value: Decimal
    stairs_enabled: bool
    first_trigger_r: Decimal
    first_offset_ticks: int
    second_trigger_r: Decimal
    second_lock_r: Decimal
    stop_method: str
    pivot_left: int
    pivot_right: int
    limit_lots: bool
    limit_margin: bool


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
    risk: RiskConfig | PivotRiskConfig

    def public(self):
        return public_values(asdict(self))


def _integer(value, low, high=None):
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError("整数不在允许范围内")
    return value


class ResearchValidationError(ValueError):
    def __init__(self, field, message, *, code='invalid_experiment'):
        super().__init__(message)
        self.code, self.field_errors = code, {field: message}


def _fail(field, message):
    raise ResearchValidationError(field, message)


def _checked(field, function, *args):
    try:
        return function(*args)
    except (ValueError, TypeError):
        _fail(field, '请填写有效的数值或日期，并核对允许范围')


def validate_contract_request(continuous, start, end):
    if (not isinstance(continuous, str) or not re.fullmatch(
            r'KQ\.m@(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+', continuous)):
        _fail('continuous', '请选择有效期货品种')
    dates = []
    for key, value in [('start', start), ('end', end)]:
        if not isinstance(value, str):
            _fail(key, '请填写有效交易日期')
        dates.append(_checked(key, date.fromisoformat, value))
    if dates[0] > dates[1]:
        _fail('end', '结束日期不能早于起始日期')
    return dict(continuous=continuous, start=str(dates[0]), end=str(dates[1]))


def validate_research_config(raw: dict) -> ResearchConfig:
    if not isinstance(raw, dict):
        _fail('config', '实验配置字段不完整或包含未知字段')
    data = dict(raw)
    config_type = ResearchConfig
    if data.get('schema_version') == 3:
        from qf.continuous_config import ContinuousConfig
        config_type = ContinuousConfig
        data.setdefault('symbol', None)
    if set(data) != {f.name for f in fields(config_type)}:
        _fail('config', '实验配置字段不完整或包含未知字段')
    version = data['schema_version']
    if (type(version) is not int or type(data['strategy_version']) is not int
            or (version, data['strategy_version']) not in ((1, 1), (2, 2), (3, 3))
            or data['strategy_id'] != 'ma_cross'):
        _fail('strategy_version', '不支持的策略或配置版本')
    risk = data.pop('risk')
    risk_type = RiskConfig if version == 1 else PivotRiskConfig
    if not isinstance(risk, dict):
        _fail('risk', '风险配置字段不完整或包含未知字段')
    risk = dict(risk)
    if version in (2, 3):
        for key, switch in [('max_lots', 'limit_lots'), ('max_margin_ratio', 'limit_margin')]:
            if risk.get(switch) is False:
                risk.setdefault(key, None)
    if set(risk) != set(risk_type.__annotations__):
        _fail('risk', '风险配置字段不完整或包含未知字段')
    if (not isinstance(data['name'], str) or not data['name'].strip()
            or len(data['name']) > 80 or any(ord(c) < 32 for c in data['name'])):
        _fail('name', '请填写不超过80字的实验名称')
    request = validate_contract_request(data['continuous'], data['start'], data['end'])
    symbol = data['symbol']
    if version == 3:
        if symbol is not None:
            _fail('symbol', '历史主力连续模式由回放时的主力映射选择合约，不固定月份')
        for key, expected in [('contract_mode', 'historical_main'),
                              ('signal_adjustment', 'causal_forward_gap_v1'),
                              ('roll_policy', 'close_then_reopen_preserve_r_v1')]:
            if data[key] != expected:
                _fail(key, '连续回测模式或政策不受支持')
    else:
        match = (re.fullmatch(r'(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.([A-Za-z]+)\d{3,4}', symbol)
                 if isinstance(symbol, str) else None)
        if not match or data['continuous'] != f'KQ.m@{match[1]}.{match[2]}':
            _fail('symbol', '请先查询并选择与品种匹配的实际月份合约')
    if _checked('bar_seconds', _integer, data['bar_seconds'], 1) not in (
            60, 300, 900, 1800, 3600, 86400):
        _fail('bar_seconds', '不支持的K线周期')
    for key in ('fast_period', 'slow_period'):
        _checked(key, _integer, data[key], 2, 200)
    if data['fast_period'] >= data['slow_period']:
        _fail('slow_period', '慢均线周期必须大于快均线')
    for key in ('start', 'end'):
        data[key] = date.fromisoformat(request[key])
    if data['precision'] not in ('minute', 'tick'):
        _fail('precision', '不支持的回测精度')
    for key in ('timeout_seconds', 'execution_timeout_seconds'):
        _checked(key, _integer, data[key], 5, 600)
    data['initial_balance'] = _checked('initial_balance', decimal_value, data['initial_balance'])
    if data['initial_balance'] <= 0:
        _fail('initial_balance', '初始虚拟资金必须大于零')
    integer_fields = ['fixed_lots', 'first_offset_ticks']
    if version == 1:
        integer_fields += ['stop_ticks', 'max_lots']
    else:
        for key in ('limit_lots', 'limit_margin'):
            if type(risk[key]) is not bool:
                _fail('risk.' + key, '请明确开启或关闭高级限制')
        if risk['stop_method'] != 'confirmed_pivot':
            _fail('risk.stop_method', '新版止损方式为最近已确认波谷／波峰')
        for key in ('pivot_left', 'pivot_right'):
            _checked('risk.' + key, _integer, risk[key], 1, 50)
        if risk['max_lots'] is not None or risk['limit_lots']:
            integer_fields.append('max_lots')
        if risk['limit_margin'] and risk['max_margin_ratio'] is None:
            _fail('risk.max_margin_ratio', '开启保证金限制后请填写比例')
    for key in integer_fields:
        _checked('risk.' + key, _integer, risk[key], 1)
    decimal_fields = ['risk_budget', 'take_profit_value',
                      'first_trigger_r', 'second_trigger_r', 'second_lock_r']
    if version == 1 or risk['max_margin_ratio'] is not None:
        decimal_fields.append('max_margin_ratio')
    for key in decimal_fields:
        risk[key] = _checked('risk.' + key, decimal_value, risk[key])
        if risk[key] <= 0:
            _fail('risk.' + key, '风险参数必须大于零')
    if (risk['sizing'] not in ('fixed', 'risk_budget')
            or risk['take_profit_mode'] not in ('r_multiple', 'amount')
            or type(risk['stairs_enabled']) is not bool):
        _fail('risk', '仓位或退出参数无效')
    if risk['max_margin_ratio'] is not None and risk['max_margin_ratio'] > 1:
        _fail('risk.max_margin_ratio', '保证金比例不能超过100%')
    if (risk['sizing'] == 'fixed' and (version == 1 or risk['limit_lots'])
            and risk['fixed_lots'] > risk['max_lots']):
        _fail('risk.fixed_lots', '固定手数超过已启用的最大手数')
    if risk['stairs_enabled'] and (
            risk['second_trigger_r'] <= risk['first_trigger_r']
            or risk['second_lock_r'] >= risk['second_trigger_r']
            or (risk['take_profit_mode'] == 'r_multiple'
                and risk['take_profit_value'] <= risk['second_trigger_r'])):
        _fail('risk.take_profit_value', '阶梯顺序或终点无效：后续阶梯必须能够到达')
    return config_type(**data, risk=risk_type(**risk))


def migrate_to_pivot(config: ResearchConfig, *, name: str) -> ResearchConfig:
    raw = config.public()
    raw['name'] = name
    if config.schema_version == 1:
        raw.update(schema_version=2, strategy_version=2)
        raw['risk'].pop('stop_ticks')
        raw['risk'].update(stop_method='confirmed_pivot', pivot_left=2, pivot_right=2,
                           limit_lots=True, limit_margin=True)
    return validate_research_config(raw)
