import pytest

from qf.backtest_plan import BacktestPlan


def item(seed='a', *, stress=False):
    return {'experiment_id': seed*32, 'revision': 1,
            'include_fee_stress': stress}


def test_plan_is_ordered_and_requires_capacity_slots_for_initial_batch():
    plan = BacktestPlan.validate({
        'capacity': 2,
        'slots': [item('a'), item('b', stress=True)],
    })
    assert plan.capacity == 2
    assert [slot.experiment_id for slot in plan.slots] == ['a'*32, 'b'*32]
    assert plan.slots[1].include_fee_stress is True
    with pytest.raises(ValueError):
        BacktestPlan.validate({'capacity': 3, 'slots': [item('a')]})


def test_added_batch_can_be_partial_but_still_bounded():
    plan = BacktestPlan.validate({
        'capacity': 3, 'slots': [item('b')],
    }, allow_partial=True)
    assert plan.capacity == 3 and len(plan.slots) == 1
    queued = BacktestPlan.validate({
        'capacity': 1, 'slots': [item('c'), item('d')],
    }, allow_partial=True)
    assert queued.capacity == 1 and len(queued.slots) == 2
    for bad in (
        {'capacity': 0, 'slots': []},
        {'capacity': 5, 'slots': [item('a')]},
        {'capacity': 1, 'slots': [item('a')]*5},
        {'capacity': 1, 'slots': [{**item('a'), 'password': 'private'}]},
        {'capacity': 1, 'slots': [{**item('a'), 'revision': True}]},
    ):
        with pytest.raises(ValueError):
            BacktestPlan.validate(bad, allow_partial=True)


def test_plan_does_not_mutate_input_and_returns_safe_public_values():
    raw = {'capacity': 1, 'slots': [item('a')]}
    plan = BacktestPlan.validate(raw)
    raw['slots'][0]['revision'] = 2
    assert plan.public() == {
        'capacity': 1,
        'slots': [{'experiment_id': 'a'*32, 'revision': 1,
                   'include_fee_stress': False}],
    }
