"""批量回测计划：页面只提交已保存实验修订，不携带路径或凭证。"""

import re
from dataclasses import dataclass

from qf.compute_backend import BackendRequest

HEX32 = re.compile(r'^[0-9a-f]{32}$')


@dataclass(frozen=True)
class PlanSlot:
    experiment_id: str
    revision: int
    include_fee_stress: bool = False
    engine_kind: str = 'tqsdk_validation'
    compute_backend: str = 'cpu'

    def public(self):
        return dict(
            experiment_id=self.experiment_id,
            revision=self.revision,
            include_fee_stress=self.include_fee_stress,
            engine_kind=self.engine_kind,
            compute_backend=self.compute_backend,
        )


@dataclass(frozen=True)
class BacktestPlan:
    capacity: int
    slots: tuple[PlanSlot, ...]

    @classmethod
    def validate(cls, raw, *, allow_partial=False):
        if not isinstance(raw, dict) or set(raw) != {'capacity', 'slots'}:
            raise ValueError('回测计划字段不完整')
        capacity = raw['capacity']
        if type(capacity) is not int or not 1 <= capacity <= 4:
            raise ValueError('并发数必须为1—4')
        values = raw['slots']
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError('回测槽位必须为1—4项')
        if not allow_partial and len(values) != capacity:
            raise ValueError('开始全部回测时，槽位数量必须等于并发数')
        slots = []
        for value in values:
            base = {
                'experiment_id',
                'revision',
                'include_fee_stress',
            }
            extended = base | {'engine_kind', 'compute_backend'}
            if (
                not isinstance(value, dict)
                or set(value) not in (base, extended)
            ):
                raise ValueError('回测槽位字段不完整')
            experiment_id = value['experiment_id']
            revision = value['revision']
            stress = value['include_fee_stress']
            engine_kind = value.get('engine_kind', 'tqsdk_validation')
            compute_backend = value.get('compute_backend', 'cpu')
            if (not isinstance(experiment_id, str)
                    or not HEX32.fullmatch(experiment_id)):
                raise ValueError('回测槽位实验编号无效')
            if type(revision) is not int or revision < 1:
                raise ValueError('回测槽位修订号无效')
            if type(stress) is not bool:
                raise ValueError('费用压力回放选项无效')
            try:
                BackendRequest.validate(
                    compute_backend, 'ma_cross', engine_kind
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from None
            slots.append(PlanSlot(
                experiment_id,
                revision,
                stress,
                engine_kind,
                compute_backend,
            ))
        return cls(capacity=capacity, slots=tuple(slots))

    def public(self):
        return {'capacity': self.capacity, 'slots': [slot.public() for slot in self.slots]}
