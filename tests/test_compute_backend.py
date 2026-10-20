import pytest

from qf.compute_backend import BackendRequest, ComputeBackend


def test_cuda_is_rejected_without_gpu_executor():
    catalog = ComputeBackend.catalog()
    assert catalog['cpu']['available'] is True
    assert catalog['cuda']['available'] is False
    assert 'GPU执行器' in catalog['cuda']['reason']
    with pytest.raises(ValueError, match='GPU执行器'):
        BackendRequest.validate('cuda', 'ma_cross', 'local_research')


def test_cpu_local_and_validation_requests_are_explicit():
    local = BackendRequest.validate('cpu', 'ma_cross', 'local_research')
    validation = BackendRequest.validate(
        'cpu', 'ma_cross', 'tqsdk_validation'
    )
    assert local.public() == {
        'mode': 'cpu',
        'strategy_id': 'ma_cross',
        'engine_kind': 'local_research',
    }
    assert validation.engine_kind == 'tqsdk_validation'


@pytest.mark.parametrize(
    'mode,strategy,engine',
    [
        ('auto', 'ma_cross', 'local_research'),
        ('cpu', 'unknown', 'local_research'),
        ('cpu', 'ma_cross', 'unknown'),
        (None, 'ma_cross', 'local_research'),
    ],
)
def test_invalid_backend_requests_are_rejected(mode, strategy, engine):
    with pytest.raises(ValueError):
        BackendRequest.validate(mode, strategy, engine)
