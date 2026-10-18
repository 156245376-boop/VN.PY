import pytest

from qf.volume_profile import calculate_volume_profile


def sample(prices=(10, 10.5, 10.5, 11), volumes=(2, 3, 5, 10)):
    return [dict(close=p, volume=v) for p, v in zip(prices, volumes, strict=True)]


def test_profile_conserves_volume_and_bins_by_close():
    result = calculate_volume_profile(sample(), {'ticks_per_row': 1}, .5)
    assert [b['volume'] for b in result['bins']] == [2, 8, 10]
    assert result['total_volume'] == 20
    assert result['poc'] == 11


def test_decimal_boundary_and_ties_are_deterministic():
    result = calculate_volume_profile(sample((.6, .2*3), (4, 6)),
                                      {'ticks_per_row': 1}, .2)
    assert len(result['bins']) == 1
    assert result['bins'][0]['volume'] == 10
    assert result['poc'] == pytest.approx(.6)


def test_zero_negative_and_limits_are_explicit():
    with pytest.raises(ValueError, match='成交量'):
        calculate_volume_profile(sample(volumes=(0, 0, 0, 0)), {}, .5)
    for rows in (sample(volumes=(-1, 1, 1, 1)), sample()*5001):
        with pytest.raises(ValueError):
            calculate_volume_profile(rows, {}, .5)
    with pytest.raises(ValueError, match='512'):
        calculate_volume_profile(sample((0, 513), (1, 1)), {'ticks_per_row': 1}, 1)
