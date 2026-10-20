"""本地快速研究与TqSdk权威回放之间的只读一致性报告。"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from qf.research_config import decimal_value, public_values

ZERO = Decimal(0)


@dataclass(frozen=True)
class ParityReport:
    status: str
    reason: str
    local_run_id: str
    validation_run_id: str
    local_engine: str
    validation_engine: str
    data_set: str | None
    signal_fingerprint: str | None
    fill_fingerprint: str | None
    signal_difference: int | None
    fill_difference: int | None
    fee_difference: str | None
    trade_count_difference: int | None
    open_position_difference: int | None
    equity_difference: str | None
    first_divergence: dict | None
    tolerance: dict

    def public(self):
        return public_values(self.__dict__)


def compare_runs(local_run, tqsdk_run, *, fee_tolerance=Decimal('0.01'),
                 equity_tolerance=Decimal('0.01')):
    fee_tolerance = decimal_value(fee_tolerance)
    equity_tolerance = decimal_value(equity_tolerance)
    if fee_tolerance < 0 or equity_tolerance < 0:
        raise ValueError('一致性容差不能为负数')
    local = _evidence(local_run)
    validation = _evidence(tqsdk_run)
    base = {
        'local_run_id': local['run_id'],
        'validation_run_id': validation['run_id'],
        'local_engine': local['engine_kind'],
        'validation_engine': validation['engine_kind'],
        'data_set': local.get('dataset_id') or validation.get('dataset_id'),
        'tolerance': {
            'fee': _text(fee_tolerance),
            'equity': _text(equity_tolerance),
        },
    }
    if (
        local['engine_kind'] != 'local_research'
        or validation['engine_kind'] != 'tqsdk_validation'
        or local['engine_kind'] == validation['engine_kind']
    ):
        return _incomplete(base, 'engine_identity_invalid')
    if (
        local['status'] != 'backtest_finished'
        or validation['status'] != 'backtest_finished'
    ):
        return _incomplete(base, 'run_not_complete')
    required = (
        'signals', 'fills', 'fees', 'closed_trade_count',
        'open_position', 'final_equity',
    )
    if any(local.get(key) is None for key in required) or any(
        validation.get(key) is None for key in required
    ):
        return _incomplete(base, 'comparison_evidence_missing')

    local_signals = _signals(local['signals'])
    validation_signals = _signals(validation['signals'])
    local_fills = _fills(local['fills'])
    validation_fills = _fills(validation['fills'])
    signal_difference, signal_first = _list_difference(
        local_signals, validation_signals, kind='signal'
    )
    fill_difference, fill_first = _list_difference(
        local_fills, validation_fills, kind='fill'
    )
    fee_difference = abs(
        decimal_value(local['fees'])-decimal_value(validation['fees'])
    )
    trade_difference = int(local['closed_trade_count'])-int(
        validation['closed_trade_count']
    )
    position_difference = int(local['open_position'])-int(
        validation['open_position']
    )
    equity_difference = abs(
        decimal_value(local['final_equity'])
        - decimal_value(validation['final_equity'])
    )
    first = signal_first or fill_first
    if first is None and fee_difference > fee_tolerance:
        first = {
            'kind': 'fee',
            'local': _text(decimal_value(local['fees'])),
            'validation': _text(decimal_value(validation['fees'])),
        }
    if first is None and trade_difference:
        first = {
            'kind': 'trade_count',
            'local': int(local['closed_trade_count']),
            'validation': int(validation['closed_trade_count']),
        }
    if first is None and position_difference:
        first = {
            'kind': 'open_position',
            'local': int(local['open_position']),
            'validation': int(validation['open_position']),
        }
    if first is None and equity_difference > equity_tolerance:
        first = {
            'kind': 'equity',
            'local': _text(decimal_value(local['final_equity'])),
            'validation': _text(decimal_value(validation['final_equity'])),
        }
    differences = (
        signal_difference
        or fill_difference
        or fee_difference > fee_tolerance
        or trade_difference
        or position_difference
        or equity_difference > equity_tolerance
    )
    return ParityReport(
        status='differences' if differences else 'matched',
        reason='first_divergence_visible' if differences else 'all_checks_within_tolerance',
        signal_fingerprint=_fingerprint(local_signals),
        fill_fingerprint=_fingerprint(local_fills),
        signal_difference=signal_difference,
        fill_difference=fill_difference,
        fee_difference=_text(fee_difference),
        trade_count_difference=trade_difference,
        open_position_difference=position_difference,
        equity_difference=_text(equity_difference),
        first_divergence=first,
        **base,
    )


def compare_saved_evidence(local_evidence, validation_evidence, **kwargs):
    return compare_runs(local_evidence, validation_evidence, **kwargs)


def _incomplete(base, reason):
    return ParityReport(
        status='incomplete',
        reason=reason,
        signal_fingerprint=None,
        fill_fingerprint=None,
        signal_difference=None,
        fill_difference=None,
        fee_difference=None,
        trade_count_difference=None,
        open_position_difference=None,
        equity_difference=None,
        first_divergence=None,
        **base,
    )


def _value(source, *names):
    for name in names:
        if isinstance(source, dict):
            if name in source:
                value = source[name]
            else:
                continue
        else:
            value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _evidence(source):
    summary = _value(source, 'summary') or {}
    details = _value(source, 'details') or {}
    signals = _value(source, 'signals')
    if signals is None:
        signals = _value(details, 'signals')
    if signals is None:
        events = _value(details, 'risk_events')
        if isinstance(events, list):
            signals = [
                event.get('payload', {}).get('signal', event.get('payload'))
                for event in events
                if event.get('kind') == 'signal'
            ]
    fills = _value(source, 'fills')
    if fills is None:
        fills = _value(details, 'fills')
    return {
        'run_id': str(
            _value(source, 'run_id')
            or _value(summary, 'run_id')
            or 'unknown'
        ),
        'engine_kind': (
            _value(source, 'engine_kind')
            or _value(summary, 'engine_kind')
        ),
        'status': _value(source, 'status') or _value(summary, 'status'),
        'dataset_id': (
            _value(source, 'dataset_id')
            or _value(summary, 'dataset_id')
            or (
                _value(summary, 'config').get('continuous')
                if isinstance(_value(summary, 'config'), dict)
                else None
            )
        ),
        'signals': signals,
        'fills': fills,
        'fees': (
            _value(source, 'fees')
            if _value(source, 'fees') is not None
            else _value(source, 'commission')
            if _value(source, 'commission') is not None
            else _value(summary, 'commission')
        ),
        'closed_trade_count': (
            _value(source, 'closed_trade_count')
            if _value(source, 'closed_trade_count') is not None
            else _value(summary, 'closed_trade_count')
        ),
        'open_position': (
            _value(source, 'open_position')
            if _value(source, 'open_position') is not None
            else _value(summary, 'open_position')
        ),
        'final_equity': (
            _value(source, 'final_equity')
            if _value(source, 'final_equity') is not None
            else _value(summary, 'final_equity')
        ),
    }


def _signals(raw):
    if not isinstance(raw, list):
        return None
    try:
        return [
            {
                'time_ns': str(item['time_ns']),
                'direction': int(item['direction']),
            }
            for item in sorted(raw, key=lambda item: int(item['time_ns']))
        ]
    except (KeyError, TypeError, ValueError):
        return None


def _fills(raw):
    if not isinstance(raw, list):
        return None
    try:
        return [
            {
                'time_ns': str(item['time_ns']),
                'symbol': str(item['symbol']),
                'direction': str(item['direction']),
                'offset': str(item['offset']),
                'volume': int(item['volume']),
                'price': _text(decimal_value(item['price'])),
                'fee': _text(decimal_value(item.get('fee', 0))),
            }
            for item in sorted(
                raw,
                key=lambda item: (
                    int(item['time_ns']),
                    str(item.get('key', '')),
                ),
            )
        ]
    except (KeyError, TypeError, ValueError):
        return None


def _list_difference(left, right, *, kind):
    if left is None or right is None:
        return None, None
    difference = 0
    first = None
    for index in range(max(len(left), len(right))):
        local = left[index] if index < len(left) else None
        validation = right[index] if index < len(right) else None
        if local == validation:
            continue
        difference += 1
        if first is None:
            first = {
                'kind': kind,
                'index': index,
                'local': local,
                'validation': validation,
            }
    return difference, first


def _fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()


def _text(value):
    return format(decimal_value(value).normalize(), 'f')
