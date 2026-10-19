from importlib import import_module


def test_progress_is_actual_time_monotone_and_save_gated():
    now = [10.0]
    progress = import_module('qf.research_progress').BacktestProgress(
        100, 200, clock=lambda: now[0])
    assert progress.update('connecting')['percent'] is None
    assert progress.update('backtesting', current_ns=150, bars=3)['percent'] == 50
    now[0] = 13
    stale = progress.update('backtesting', current_ns=130, bars=2)
    assert stale['current_ns'] == 150 and stale['completed_bars'] == 3
    assert stale['last_advance_age_seconds'] == 3
    assert progress.update('saving', current_ns=2145888000000000000)['current_ns'] == 150
    assert progress.update('backtesting', current_ns=200)['percent'] == 99
    assert progress.update('failed')['percent'] != 100
    final = progress.update('completed', success=True)
    assert final['finished'] and final['percent'] == 100
    assert final['elapsed_seconds'] == 3
