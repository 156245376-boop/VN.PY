"""本地历史数据的请求、权限与覆盖契约。"""

import re
from dataclasses import dataclass
from datetime import date

CONTINUOUS = re.compile(r'^KQ\.m@(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+$')
SYMBOL = re.compile(r'^(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{3,4}$')
PRECISIONS = {'minute', 'tick'}
CAPABILITY_STATUSES = {'available', 'permission_required', 'unsupported', 'error'}
COVERAGE_ISSUES = {'duplicate_bar', 'invalid_bar', 'time_order', 'long_gap',
                   'calendar_mismatch'}


@dataclass(frozen=True)
class DataRequest:
    continuous: str
    symbol: str | None
    bar_seconds: int
    start: date
    end: date
    precision: str

    def validate(self):
        if not isinstance(self.continuous, str) or not CONTINUOUS.fullmatch(self.continuous):
            raise ValueError('连续合约品种无效')
        if self.symbol is not None and (
                not isinstance(self.symbol, str) or not SYMBOL.fullmatch(self.symbol)):
            raise ValueError('实际合约无效')
        if type(self.bar_seconds) is not int or self.bar_seconds < 1:
            raise ValueError('K线周期无效')
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError('数据日期范围无效')
        if self.precision not in PRECISIONS:
            raise ValueError('数据精度无效')
        return self

    def key(self):
        self.validate()
        return '|'.join((
            self.continuous, self.symbol or '', str(self.bar_seconds),
            self.start.isoformat(), self.end.isoformat(), self.precision))

    def public(self):
        self.validate()
        return {
            'continuous': self.continuous, 'symbol': self.symbol,
            'bar_seconds': self.bar_seconds, 'start': self.start.isoformat(),
            'end': self.end.isoformat(), 'precision': self.precision,
        }

    @classmethod
    def from_public(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {
                'continuous', 'symbol', 'bar_seconds', 'start', 'end', 'precision'}:
            raise ValueError('数据请求字段无效')
        try:
            value = cls(
                continuous=raw['continuous'], symbol=raw['symbol'],
                bar_seconds=raw['bar_seconds'],
                start=date.fromisoformat(raw['start']) if isinstance(raw['start'], str)
                else raw['start'],
                end=date.fromisoformat(raw['end']) if isinstance(raw['end'], str)
                else raw['end'],
                precision=raw['precision'])
        except (TypeError, ValueError):
            raise ValueError('数据请求字段无效') from None
        return value.validate()


@dataclass(frozen=True)
class CoverageReport:
    expected_days: list[date]
    observed_days: list[date]
    issues: list[str]

    def validate(self):
        for values, name in ((self.expected_days, '预期交易日'),
                             (self.observed_days, '实际交易日')):
            if (not isinstance(values, list)
                    or any(type(value) is not date for value in values)
                    or len(values) != len(set(values))):
                raise ValueError(f'{name}无效')
        if not self.expected_days or not set(self.observed_days) <= set(self.expected_days):
            raise ValueError('实际交易日超出预期交易日')
        if (not isinstance(self.issues, list)
                or any(issue not in COVERAGE_ISSUES for issue in self.issues)):
            raise ValueError('覆盖问题无效')
        return self

    def missing_days(self):
        self.validate()
        observed = set(self.observed_days)
        return [day for day in self.expected_days if day not in observed]

    def complete(self):
        self.validate()
        return not self.issues and not self.missing_days()

    def public(self):
        self.validate()
        return {
            'expected_days': [day.isoformat() for day in self.expected_days],
            'observed_days': [day.isoformat() for day in self.observed_days],
            'missing_days': [day.isoformat() for day in self.missing_days()],
            'issues': list(self.issues), 'complete': self.complete(),
        }


@dataclass(frozen=True)
class DataCapability:
    status: str
    reason: str
    minute_available: bool
    tick_available: bool
    source: str

    def validate(self):
        if (self.status not in CAPABILITY_STATUSES
                or not isinstance(self.reason, str)
                or type(self.minute_available) is not bool
                or type(self.tick_available) is not bool
                or not isinstance(self.source, str)):
            raise ValueError('数据能力状态无效')
        return self

    def public(self):
        self.validate()
        return {
            'status': self.status, 'reason': self.reason,
            'minute_available': self.minute_available,
            'tick_available': self.tick_available, 'source': self.source,
        }
