import pytest

from qf.ma_cross import completed_cross


def rows(values):
    return [dict(datetime=(i+1)*60_000_000_000, close=v) for i, v in enumerate(values)]


@pytest.mark.parametrize('values,want', [([3, 2, 1, 2, 3, -9999], 1),
    ([1, 2, 3, 2, 1, 9999], -1), ([1, 1, 1, 1, 2, 0], 1),
    ([2, 2, 2, 2, 1, 0], -1)])
def test_cross_uses_two_completed_windows_not_live_bar(values, want):
    signal = completed_cross(rows(values), 2, 3, completed_ns=360_000_000_000)
    assert signal.direction == want
    assert signal.bar_start_ns == 300_000_000_000


def test_warmup_duplicate_time_invalid_price_yields_no_signal():
    assert completed_cross(rows([1, 2, 3, 99]), 2, 3, completed_ns=240_000_000_000) is None
    for values in ([1, 2, float('nan'), 2, 3, 0], [1, 2, -1, 2, 3, 0]):
        assert completed_cross(rows(values), 2, 3, completed_ns=360_000_000_000) is None
    bad = rows([3, 2, 1, 2, 3, 0])
    bad[3]['datetime'] = bad[2]['datetime']
    assert completed_cross(bad, 2, 3, completed_ns=360_000_000_000) is None
