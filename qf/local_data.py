"""从规范化历史库构建本地连续信号数据。"""

from dataclasses import dataclass, field

import pandas as pd

from qf.trade_risk import ContractSpec


@dataclass(frozen=True)
class LocalFrame:
    dataset_id: str
    frame: pd.DataFrame
    symbols: tuple[str, ...]
    specs: dict[str, ContractSpec] = field(default_factory=dict)
    bar_seconds: int = 60
    precision: str = 'minute'
    continuous: str = ''
    coverage_complete: bool = False
    mapping: tuple[dict, ...] = field(default_factory=tuple)


def load_continuous_frame(store, dataset_id):
    bars = store.load_bars(dataset_id).sort_values(
        ['time_ns', 'symbol'], kind='stable').reset_index(drop=True)
    if bars.empty:
        raise ValueError('数据集没有K线')
    if bars['time_ns'].duplicated().any():
        raise ValueError('数据集同一时间存在多个实际合约K线')
    if not bars['time_ns'].is_monotonic_increasing:
        raise ValueError('数据集K线时间顺序无效')
    mappings = store.load_mapping(dataset_id)
    if not mappings:
        raise ValueError('数据集没有历史主力映射')
    offsets = []
    for row in bars.itertuples(index=False):
        candidates = [item for item in mappings
                      if item['new_symbol'] == row.symbol
                      and item['time_ns'] <= row.time_ns]
        if not candidates:
            raise ValueError('K线缺少当时已经生效的历史主力映射')
        offsets.append(float(candidates[-1]['offset']))
    result = bars.copy()
    for price_field in ('open', 'high', 'low', 'close'):
        result['actual_' + price_field] = result[price_field].astype(float)
        result[price_field] = (
            result['actual_' + price_field]-pd.Series(offsets, dtype=float)
        )
    result['offset'] = offsets
    request = store.dataset_request(dataset_id)
    result['completed_ns'] = result['time_ns'].astype('int64') + request.bar_seconds*1_000_000_000
    result['completed'] = result['completed'].astype(bool)
    specs = {item['symbol']: ContractSpec(
        item['symbol'], item['price_tick'], item['volume_multiple'],
        int(item.get('min_open_lots', 1)), int(item.get('lot_step', 1)),
        item['margin_per_lot'], item['commission_per_lot'],
        item.get('cost_source', 'historical_data'))
        for item in store.load_instruments(dataset_id)}
    missing = sorted(set(result['symbol'])-set(specs))
    if missing:
        raise ValueError('缺少实际合约规格: '+', '.join(missing))
    coverage = store.coverage(dataset_id)
    return LocalFrame(dataset_id=dataset_id, frame=result,
                      symbols=tuple(sorted(result['symbol'].unique())), specs=specs,
                      bar_seconds=request.bar_seconds, precision=request.precision,
                      continuous=request.continuous,
                      coverage_complete=coverage.complete(),
                      mapping=tuple(dict(item) for item in mappings))
