import pandas as pd
from test_continuous_config import continuous_data
from test_continuous_risk import spec

from qf.continuous_journal import ContinuousJournal
from qf.local_dataset_builder import (
    build_local_dataset_from_validation,
    ensure_local_dataset,
)
from qf.research_config import validate_research_config
from qf.runtime import provenance


def config():
    raw = continuous_data()
    raw.update(
        start='2025-01-02',
        end='2025-01-02',
        bar_seconds=60,
        precision='minute',
    )
    return validate_research_config(raw)


def write_validation(root):
    cfg = config()
    journal = ContinuousJournal.create(root, 'backtest', cfg, provenance())
    try:
        journal.set('engine_kind', 'tqsdk_validation')
        journal.set('status', 'backtest_finished')
        journal.set('reason', 'historical_replay_completed')
        journal.set('coverage_check', {
            'status': 'verified',
            'missing_days': [],
            'reasons': [],
        })
        journal.record_spec('SHFE.rb2505', spec())
        journal.record_mapping({
            'changed': True,
            'old_symbol': None,
            'new_symbol': 'SHFE.rb2505',
            'detected_ns': 1,
            'reference_ns': None,
            'previous_offset': 0,
            'offset': 0,
        })
        stamp = int(pd.Timestamp('2025-01-02 09:00', tz='Asia/Shanghai').value)
        raw = {
            'datetime': stamp,
            'end_ns': stamp+60_000_000_000,
            'open': 280,
            'high': 281,
            'low': 279,
            'close': 280,
            'volume': 10,
            'close_oi': 20,
        }
        journal.capture_signal({
            **raw,
            'open': 280,
            'high': 281,
            'low': 279,
            'close': 280,
            'completed': True,
            'completed_at_ns': stamp+60_000_000_000,
            'raw': raw,
            'source_symbol': 'SHFE.rb2505',
            'offset': 0,
            'trading_day': '2025-01-02',
        })
        journal.checkpoint_integrity()
        return cfg, journal.path.name
    finally:
        journal.close()


def test_builder_creates_reusable_contract_dataset_from_validation_run(tmp_path):
    cfg, run_id = write_validation(tmp_path)
    dataset_id, local = build_local_dataset_from_validation(
        tmp_path, run_id, cfg
    )
    assert local.dataset_id == dataset_id
    assert local.coverage_complete is True
    assert local.frame.iloc[0]['actual_close'] == 280
    assert local.frame.iloc[0]['close'] == 280
    assert local.specs['SHFE.rb2505'].commission_per_lot == 2
    assert ensure_local_dataset(tmp_path, cfg) == dataset_id


def test_builder_refuses_incomplete_validation_result(tmp_path):
    cfg, run_id = write_validation(tmp_path)
    journal = ContinuousJournal(tmp_path/run_id)
    try:
        journal.set('coverage_check', {
            'status': 'incomplete',
            'missing_days': ['2025-01-02'],
            'reasons': ['missing_trading_days'],
        })
        journal.checkpoint_integrity()
    finally:
        journal.close()
    try:
        build_local_dataset_from_validation(tmp_path, run_id, cfg)
    except ValueError as exc:
        assert '覆盖' in str(exc)
    else:
        raise AssertionError('incomplete validation must not become local data')


def test_builder_rejects_tick_precision(tmp_path):
    cfg, run_id = write_validation(tmp_path)
    tick = cfg.public() | {'precision': 'tick'}
    with_tick = validate_research_config(tick)
    try:
        build_local_dataset_from_validation(tmp_path, run_id, with_tick)
    except ValueError as exc:
        assert 'Tick' in str(exc)
    else:
        raise AssertionError('tick precision must require a tick path')
