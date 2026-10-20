"""计算后端能力目录；不把无执行器的CUDA显示成可选。"""

from dataclasses import dataclass

ENGINE_KINDS = {'local_research', 'tqsdk_validation'}
STRATEGIES = {'ma_cross'}
BACKENDS = {'cpu', 'cuda'}


@dataclass(frozen=True)
class BackendRequest:
    mode: str
    strategy_id: str
    engine_kind: str

    @classmethod
    def validate(cls, mode, strategy_id, engine_kind):
        if mode not in BACKENDS:
            raise ValueError('计算后端必须明确选择CPU或CUDA')
        if strategy_id not in STRATEGIES:
            raise ValueError('策略没有对应的计算执行器')
        if engine_kind not in ENGINE_KINDS:
            raise ValueError('研究引擎身份无效')
        if mode == 'cuda':
            raise ValueError('CUDA不可用：当前没有经过验证的GPU执行器')
        return cls(mode, strategy_id, engine_kind)

    def public(self):
        return {
            'mode': self.mode,
            'strategy_id': self.strategy_id,
            'engine_kind': self.engine_kind,
        }


class ComputeBackend:
    @staticmethod
    def catalog():
        return {
            'cpu': {
                'available': True,
                'reason': 'CPU可用；独立进程执行，单任务内部保持因果顺序。',
            },
            'cuda': {
                'available': False,
                'reason': 'CUDA不可用：当前双均线研究引擎没有经过验证的GPU执行器。',
            },
        }
