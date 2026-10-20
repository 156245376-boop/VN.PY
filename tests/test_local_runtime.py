from test_local_dataset_builder import write_validation

from qf.local_dataset_builder import build_local_dataset_from_validation
from qf.local_runtime import execute_local_research
from qf.research_results import read_run, summarize_run


def test_local_runtime_loads_cached_data_and_saves_research_result(tmp_path):
    cfg, validation_id = write_validation(tmp_path)
    dataset_id, _local = build_local_dataset_from_validation(
        tmp_path, validation_id, cfg
    )
    stages = []
    result = execute_local_research(
        cfg,
        tmp_path,
        dataset_id,
        progress=lambda stage, **fields: stages.append((stage, fields)),
        stop_requested=lambda: False,
    )
    assert result['status'] == 'backtest_finished'
    assert result['engine_kind'] == 'local_research'
    summary = summarize_run(tmp_path, result['run_id'])
    assert summary['dataset_id'] == dataset_id
    assert summary['engine_kind'] == 'local_research'
    assert read_run(tmp_path, result['run_id'])['compute_backend'] == 'cpu'
    assert [stage for stage, _fields in stages] == [
        'loading_data',
        'backtesting',
        'saving',
        'saved',
    ]


def test_local_runtime_cancellation_is_persisted(tmp_path):
    cfg, validation_id = write_validation(tmp_path)
    dataset_id, _local = build_local_dataset_from_validation(
        tmp_path, validation_id, cfg
    )
    result = execute_local_research(
        cfg,
        tmp_path,
        dataset_id,
        stop_requested=lambda: True,
    )
    assert result['status'] == 'stopped'
    summary = summarize_run(tmp_path, result['run_id'])
    assert summary['reason'] == 'requested_stop'
