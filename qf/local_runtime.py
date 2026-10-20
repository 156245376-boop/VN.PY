"""快速研究任务运行入口：读取本机数据、执行、批量保存。"""

from pathlib import Path

from qf.history_store import HistoryStore
from qf.local_backtest import LocalBacktestEngine
from qf.local_data import load_continuous_frame
from qf.local_results import save_local_result, summarize_local_run
from qf.runtime import provenance


def execute_local_research(config, results_root, dataset_id, *,
                           fee_multiplier=1, progress=None,
                           stop_requested=None, experiment_ref=None):
    results_root = Path(results_root)
    progress = progress or (lambda *_args, **_kwargs: None)
    stop_requested = stop_requested or (lambda: False)
    progress('loading_data', percent=None, dataset_id=dataset_id)
    store = HistoryStore(results_root/'history')
    dataset = load_continuous_frame(store, dataset_id)
    if dataset.continuous != config.continuous:
        raise ValueError('本机数据品种与实验不一致')

    def local_progress(stage, **fields):
        progress(stage, details=fields, dataset_id=dataset_id)

    result = LocalBacktestEngine(
        fee_multiplier=fee_multiplier
    ).run(
        dataset,
        config,
        progress=local_progress,
        cancel=stop_requested,
    )
    progress(
        'saving',
        percent=None,
        dataset_id=dataset_id,
        fill_count=len(result.fills),
    )
    source = provenance() | {
        'dataset_id': dataset_id,
        'engine_kind': 'local_research',
        'experiment_ref': experiment_ref,
        'cost_source': 'normalized_contract_specs',
    }
    run_id = save_local_result(results_root, result, source)
    summary = summarize_local_run(results_root, run_id)
    progress(
        'saved',
        percent=100,
        run_id=run_id,
        dataset_id=dataset_id,
        fill_count=len(result.fills),
    )
    return {
        'run_id': run_id,
        'status': result.status,
        'reason': result.reason,
        'engine_kind': 'local_research',
        'dataset_id': dataset_id,
        'summary': summary,
        'failure_context': {},
    }
