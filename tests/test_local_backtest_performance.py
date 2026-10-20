from local_backtest_perf_probe import run_once


def test_cached_local_backtest_is_repeatable_without_sdk_io():
    first = run_once(8000)
    second = run_once(8000)
    assert first['status'] == 'backtest_finished'
    assert first['fingerprint'] == second['fingerprint']
    assert first['profile']['bars_processed'] == 8000
    assert first['signal_count'] > 0
    assert first['elapsed_seconds'] < 20
