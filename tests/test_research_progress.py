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


def test_warmup_tracks_actual_time_without_claiming_trading_progress():
    now = [10.0]
    progress = import_module('qf.research_progress').BacktestProgress(
        100, 200, warmup_start_ns=20, clock=lambda: now[0])
    initial = progress.update('warmup', current_ns=20, bars=1)
    assert initial['current_ns'] == 20 and initial['warmup_percent'] == 0
    now[0] = 15
    halfway = progress.update('warmup', current_ns=60, bars=640)
    assert halfway['current_ns'] == 60 and halfway['warmup_percent'] == 50
    assert halfway['percent'] == 0 and halfway['fill_count'] == 0
    assert halfway['trading_start_ns'] == 100
    assert halfway['last_advance_age_seconds'] == 0
    stopped = progress.update('stopped', current_ns=60)
    assert stopped['warmup_percent'] == 50 and not stopped['finished']
    active = progress.update('backtesting', current_ns=110, bars=650, fills=1)
    assert active['warmup_percent'] is None and active['percent'] == 10
    assert active['fill_count'] == 1
