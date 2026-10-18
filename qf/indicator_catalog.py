"""有限指标目录；公式归天勤，参数不执行表达式。"""

import copy
import math
import re

CATALOG = {
    'ma': ('简单均线 MA', 'main', {'periods': [5, 10, 20, 60]}),
    'ema': ('指数均线 EMA', 'main', {'periods': [12, 26]}),
    'boll': ('布林带 BOLL', 'main', {'n': 20, 'p': 2}),
    'sar': ('抛物线 SAR', 'main', {'n': 4, 'step': .02, 'max': .2}),
    'vp': ('成交量分布 VP（估算）', 'main', {'mode': 'screen', 'ticks_per_row': 0,
                                          'range': None}),
    'macd': ('MACD', 'sub', {'short': 12, 'long': 26, 'm': 9}),
    'kdj': ('随机指标 KDJ', 'sub', {'n': 9, 'm1': 3, 'm2': 3}),
    'rsi': ('相对强弱 RSI', 'sub', {'n': 6}),
    'atr': ('真实波幅 ATR', 'sub', {'n': 14}),
    'cci': ('顺势指标 CCI', 'sub', {'n': 14}),
    'dmi': ('趋向指标 DMI', 'sub', {'n': 14, 'm': 6}),
    'obv': ('能量潮 OBV', 'sub', {}),
    'zscore': ('标准分数 Z-Score', 'sub', {'source': 'close', 'mean_length': 10,
                                        'std_length': 10, 'reference_lines': True}),
    'volume': ('成交量', 'sub', {}), 'oi': ('持仓量', 'sub', {}),
}
COLORS = ['#dc8c32', '#377bd1', '#ac57b1', '#25896b', '#d9534f', '#73828c',
          '#bfab36', '#589bba']


def indicator_catalog() -> dict:
    return {key: {'name': name, 'board': board, 'params': copy.deepcopy(params)}
            for key, (name, board, params) in CATALOG.items()}


def default_item(kind: str, ident: str | None = None) -> dict:
    if kind not in CATALOG:
        raise ValueError('未知指标')
    return {'id': ident or kind, 'type': kind, 'visible': True,
            'params': copy.deepcopy(CATALOG[kind][2]), 'height': 160,
            'style': {'colors': COLORS.copy(), 'width': 2, 'side': 'right',
                      'width_pct': 25, 'transparency': 45, 'poc': True}}


def number(value, low, high, *, integer=False):
    if (type(value) not in ((int,) if integer else (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError('指标参数超出允许范围')
    return value


def validate_item(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {'id', 'type', 'visible', 'params',
                                               'style', 'height'}:
        raise ValueError('指标字段无效')
    kind = raw['type']
    if not isinstance(kind, str) or kind not in CATALOG:
        raise ValueError('未知指标')
    if (raw['id'] not in ([kind] if kind != 'vp' else ['vp', 'vp-fixed'])
            or type(raw['visible']) is not bool):
        raise ValueError('指标标识无效')
    p, style = raw['params'], raw['style']
    if not isinstance(p, dict) or set(p) != set(CATALOG[kind][2]):
        raise ValueError('指标参数无效')
    for key, value in p.items():
        if key == 'periods':
            if (not isinstance(value, list) or not 1 <= len(value) <= 8
                    or len(set(map(str, value))) != len(value)):
                raise ValueError('均线周期需要 1–8 个且不重复')
            for period in value:
                number(period, 1, 1000, integer=True)
        elif key in ('n', 'm', 'm1', 'm2', 'short', 'long', 'mean_length', 'std_length'):
            number(value, 1, 1000, integer=True)
        elif key == 'source' and value not in ('open', 'high', 'low', 'close'):
            raise ValueError('Z-Score 输入须为开、高、低或收盘价')
        elif key == 'reference_lines' and type(value) is not bool:
            raise ValueError('参考线开关无效')
        elif key == 'p':
            number(value, .01, 100)
        elif key in ('step', 'max'):
            number(value, .000001, 1)
        elif key == 'ticks_per_row':
            number(value, 0, 10000, integer=True)
        elif key == 'mode' and value not in ('screen', 'fixed'):
            raise ValueError('VP 范围模式无效')
        elif key == 'range' and value is not None:
            if (not isinstance(value, dict) or set(value) != {'symbol', 'start_ns', 'end_ns'}
                    or not isinstance(value['symbol'], str)
                    or not re.fullmatch(r'(?:KQ\.m@)?(?:SHFE|DCE|CZCE|CFFEX|INE|GFEX)'
                                        r'\.[A-Za-z]+\d{0,4}', value['symbol'])
                    or any(not isinstance(value[k], str) or not re.fullmatch(r'\d{16,20}', value[k])
                           for k in ('start_ns', 'end_ns'))
                    or int(value['start_ns']) >= int(value['end_ns'])):
                raise ValueError('VP 时间区间无效')
    if kind == 'macd' and p['short'] >= p['long']:
        raise ValueError('MACD 短周期必须小于长周期')
    if kind == 'sar' and p['step'] > p['max']:
        raise ValueError('SAR 步长不能超过上限')
    if not isinstance(style, dict) or set(style) != set(default_item(kind)['style']):
        raise ValueError('指标样式无效')
    if (not isinstance(style['colors'], list) or not 1 <= len(style['colors']) <= 8
            or any(not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c)
                   for c in style['colors']) or style['side'] not in ('left', 'right')
            or type(style['poc']) is not bool):
        raise ValueError('指标颜色或位置无效')
    for key, low, high in [('width', 1, 6), ('width_pct', 10, 40), ('transparency', 10, 90)]:
        number(style[key], low, high)
    number(raw['height'], 120, 600, integer=True)
    return copy.deepcopy(raw)
