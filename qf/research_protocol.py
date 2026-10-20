"""父子回测进程的冻结身份与有界消息协议。"""

import json
import re
import uuid
from dataclasses import dataclass

from qf.compute_backend import BackendRequest
from qf.research_config import validate_research_config

HEX32 = re.compile(r'^[0-9a-f]{32}$')
STREAMS = {'status', 'frame', 'terminal'}
KINDS = {'ready', 'state', 'frame', 'result', 'error'}


@dataclass(frozen=True)
class FrozenBacktest:
    job_id: str
    epoch: str
    config_json: str
    experiment_ref_json: str
    fee_multiplier: int
    source_json: str
    engine_kind: str = 'tqsdk_validation'
    compute_backend: str = 'cpu'

    @property
    def config(self):
        return json.loads(self.config_json)

    @property
    def experiment_ref(self):
        return json.loads(self.experiment_ref_json)

    @property
    def source(self):
        return json.loads(self.source_json)


def freeze_backtest(config, experiment_ref=None, *, job_id=None, epoch=None,
                    fee_multiplier=1, source=None,
                    engine_kind='tqsdk_validation', compute_backend='cpu'):
    config = validate_research_config(config.public())
    if config.schema_version not in (2, 3) or fee_multiplier not in (1, 2):
        raise ValueError('回测任务类型无效')
    BackendRequest.validate(compute_backend, config.strategy_id, engine_kind)
    job_id = job_id or uuid.uuid4().hex
    epoch = epoch or uuid.uuid4().hex
    if not HEX32.fullmatch(job_id) or not HEX32.fullmatch(epoch):
        raise ValueError('回测任务身份无效')
    return FrozenBacktest(job_id, epoch,
                          json.dumps(config.public(), ensure_ascii=False, sort_keys=True),
                          json.dumps(experiment_ref or {}, ensure_ascii=False, sort_keys=True),
                          fee_multiplier,
                          json.dumps(source or {}, ensure_ascii=False, sort_keys=True),
                          engine_kind,
                          compute_backend)


def message(task, *, run_id, stream, seq, kind, payload):
    if (stream not in STREAMS or kind not in KINDS or type(seq) is not int
            or seq < 1 or not isinstance(payload, dict)):
        raise ValueError('研究消息内容无效')
    return dict(job_id=task.job_id, epoch=task.epoch, run_id=run_id,
                stream=stream, seq=seq, kind=kind, payload=payload)


def accept_message(task, raw, *, last_seq, bound_run_id=None):
    if not isinstance(raw, dict) or set(raw) != {
            'job_id', 'epoch', 'run_id', 'stream', 'seq', 'kind', 'payload'}:
        return None
    if raw['job_id'] != task.job_id or raw['epoch'] != task.epoch:
        return None
    if raw['stream'] not in STREAMS or raw['kind'] not in KINDS:
        return None
    if type(raw['seq']) is not int or raw['seq'] <= last_seq.get(raw['stream'], 0):
        return None
    if bound_run_id is not None and raw['run_id'] != bound_run_id:
        return None
    if not isinstance(raw['payload'], dict):
        return None
    return raw
