"""固定输入的本地回测性能探针；只输出证据，不预设速度结论。"""

import argparse
import json
import math
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_continuous_config import continuous_data

from qf.local_backtest import LocalBacktestEngine
from qf.local_data import LocalFrame
from qf.research_config import validate_research_config
from qf.trade_risk import ContractSpec

SYMBOL = 'SHFE.rb2505'
MINUTE = 60_000_000_000


def build_case(rows):
    start = int(pd.Timestamp('2025-01-02 09:00', tz='Asia/Shanghai').value)
    values = []
    for index in range(rows):
        close = 3000+20*math.sin(index/17)+8*math.sin(index/5)+index*.002
        values.append({
            'symbol': SYMBOL,
            'duration': 60,
            'time_ns': start+index*MINUTE,
            'open': close-1,
            'high': close+2,
            'low': close-2,
            'close': close,
            'actual_open': close-1,
            'actual_high': close+2,
            'actual_low': close-2,
            'actual_close': close,
            'offset': 0,
            'volume': 10,
            'close_oi': 20,
            'completed': True,
            'completed_ns': start+index*MINUTE+MINUTE,
        })
    end = pd.Timestamp(start+(rows-1)*MINUTE, tz='UTC').tz_convert(
        'Asia/Shanghai'
    ).date()
    raw = continuous_data()
    raw.update(
        start='2025-01-02',
        end=str(end),
        bar_seconds=60,
        fast_period=5,
        slow_period=20,
        initial_balance='100000',
    )
    raw['risk'].update(
        sizing='fixed',
        fixed_lots=1,
        pivot_left=2,
        pivot_right=2,
        stairs_enabled=True,
        first_trigger_r=Decimal('1'),
        first_offset_ticks=1,
        second_trigger_r=Decimal('2'),
        second_lock_r=Decimal('0.5'),
        take_profit_mode='r_multiple',
        take_profit_value=Decimal('3'),
        limit_lots=False,
        limit_margin=False,
        max_lots=None,
        max_margin_ratio=None,
    )
    config = validate_research_config(raw)
    dataset = LocalFrame(
        dataset_id='performance-fixture',
        frame=pd.DataFrame(values),
        symbols=(SYMBOL,),
        specs={
            SYMBOL: ContractSpec(
                SYMBOL,
                Decimal('1'),
                Decimal('10'),
                1,
                1,
                Decimal('3000'),
                Decimal('2'),
                'fixture',
            )
        },
        bar_seconds=60,
        precision='minute',
        continuous='KQ.m@SHFE.rb',
        coverage_complete=True,
    )
    return dataset, config


def run_once(rows):
    load_started = time.perf_counter()
    dataset, config = build_case(rows)
    load_seconds = time.perf_counter()-load_started
    started = time.perf_counter()
    result = LocalBacktestEngine().run(
        dataset,
        config,
        progress=None,
        cancel=lambda: False,
    )
    elapsed = time.perf_counter()-started
    return {
        'elapsed_seconds': elapsed,
        'load_seconds': load_seconds,
        'rows': len(dataset.frame),
        'signal_count': len(result.signals),
        'fill_count': len(result.fills),
        'closed_trade_count': result.closed_trade_count,
        'fingerprint': result.fingerprint(),
        'status': result.status,
        'profile': result.profile,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=8000)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    if args.rows < 100 or args.repeat < 1:
        raise SystemExit('rows >= 100 and repeat >= 1')
    values = [run_once(args.rows) for _ in range(args.repeat)]
    fingerprints = {item['fingerprint'] for item in values}
    report = {
        'rows': args.rows,
        'repeat': args.repeat,
        'median_elapsed_seconds': statistics.median(
            item['elapsed_seconds'] for item in values
        ),
        'median_load_seconds': statistics.median(
            item['load_seconds'] for item in values
        ),
        'fingerprints': sorted(fingerprints),
        'deterministic': len(fingerprints) == 1,
        'runs': values,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
