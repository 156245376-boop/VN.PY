"""合成SDK性能探针；只报告展示与处理开销，不代表真实网络耗时。"""

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]

from pivot_sdk import sdk_for_pivot  # noqa: E402
from research_helpers import pivot_config_data  # noqa: E402

from qf.research_config import validate_research_config  # noqa: E402
from qf.research_runtime import execute_research  # noqa: E402


def one(mode):
    raw = pivot_config_data()
    raw['end'] = raw['start']
    config = validate_research_config(raw)
    frames = []
    started = time.perf_counter()
    result = execute_research(
        'backtest', config, Path(tempfile.mkdtemp(prefix='qf-perf-')),
        ('offline', 'not-a-real-password'), sdk=sdk_for_pivot(),
        view_progress=frames.append, view_requested=(lambda: mode == 'watch'))
    return {
        'mode': mode,
        'elapsed_seconds': round(time.perf_counter()-started, 4),
        'frame_builds': len(frames),
        'status': result['status'],
        'fill_count': result['summary']['fill_count'],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    results = []
    for mode in ('fast', 'watch'):
        samples = [one(mode) for _ in range(max(1, args.repeat))]
        results.append({
            'mode': mode,
            'median_seconds': round(statistics.median(
                sample['elapsed_seconds'] for sample in samples), 4),
            'frame_builds': samples[0]['frame_builds'],
            'fill_count': samples[0]['fill_count'],
            'status': samples[0]['status'],
        })
    if next(x for x in results if x['mode'] == 'fast')['frame_builds'] != 0:
        raise SystemExit('fast mode constructed chart frames')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
