"""研究后台唯一工作线程；公开状态不包含凭证或SDK原始对象。"""

import copy
import logging
import threading
import time
import uuid
from pathlib import Path

from qf.research_config import public_values, validate_research_config
from qf.research_runtime import discover_contracts, execute_research
from qf.trade_risk import RiskState

STATES = {'created', 'connecting', 'active', 'observing', 'stopped', 'failed', 'frozen',
          'backtest_finished', 'discovering', 'contracts_ready'}


def wire(value):
    if isinstance(value, dict):
        return {key: str(item) if key.endswith('_ns') and type(item) is int else wire(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [wire(item) for item in value]
    return public_values(value)


class ResearchSession:
    def __init__(self, root: Path, *, execute_fn=None, discover_fn=None):
        self.root = Path(root)
        self.execute_fn, self.discover_fn = execute_fn or execute_research, discover_fn
        self._lock = threading.RLock()
        self._stop, self._flatten = threading.Event(), threading.Event()
        self.thread = None
        self._state = {'status': 'created', 'risk': {}, 'contracts': [], 'contract_request': None}
        self._closing_at = None
        self._timeout = 30
        self._live = None
        self._request_id = 0
        self._progress_at = None

    def live_snapshot(self):
        with self._lock:
            return wire(copy.deepcopy(self._live))

    def _view_progress(self, snapshot):
        with self._lock:
            self._live = copy.deepcopy(snapshot)
            self._state['entry_plan'] = copy.deepcopy(snapshot.get('entry_plan'))

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def snapshot(self):
        with self._lock:
            value = copy.deepcopy(self._state | {'running': self.running})
            if self.running and self._progress_at is not None and value.get('progress'):
                delta = max(0, time.monotonic()-self._progress_at)
                for key in ('elapsed_seconds', 'last_advance_age_seconds'):
                    value['progress'][key] = round(value['progress'].get(key, 0)+delta, 1)
            return wire(value)

    def _progress(self, stage, **fields):
        with self._lock:
            if stage == 'connecting':
                self._state['status'] = 'connecting'
            if stage == 'research_progress':
                self._state['progress'] = wire(copy.deepcopy(fields['details']))
                self._progress_at = time.monotonic()
            if stage == 'research_state':
                for key in ('phase', 'equity', 'commission', 'symbol', 'precision', 'run_id'):
                    if key in fields:
                        self._state[key] = fields[key]
                if isinstance(fields.get('risk'), dict):
                    self._state['risk'] = {k: v for k, v in fields['risk'].items()
                                           if k in RiskState.__annotations__}
                self._state['status'] = 'active' if self._state.get('activate') else 'observing'

    def start(self, mode, config, credentials, *, activate=False, resume=None, experiment_ref,
              fee_multiplier=1):
        with self._lock:
            if self.running or self._closing_at is not None:
                raise ValueError('已有研究任务或正在退出')
            if (mode not in ('backtest', 'paper') or type(activate) is not bool
                    or type(fee_multiplier) is not int or fee_multiplier not in (1, 2)
                    or (mode == 'paper' and fee_multiplier != 1)):
                raise ValueError('研究模式无效')
            if mode != 'paper' and (activate or resume):
                raise ValueError('仅快期模拟允许启用或恢复')
            config = validate_research_config(config.public())
            self._timeout = config.execution_timeout_seconds
            self._stop.clear()
            self._flatten.clear()
            self._live = None
            self._progress_at = None
            self._state.update(status='connecting', phase='flat', risk={}, mode=mode,
                activate=activate or mode == 'backtest', config=config.public(),
                experiment_ref=copy.deepcopy(experiment_ref), result=None, run_id=None,
                job_id=uuid.uuid4().hex, progress=None, entry_plan=None, reason=None,
                equity=None, commission=None)
            self.thread = threading.Thread(target=self._run,
                args=(mode, config, credentials, activate, resume, fee_multiplier,
                      copy.deepcopy(experiment_ref)), daemon=True)
            self.thread.start()
            return {'ok': True, 'reason': '已开始研究任务。', 'job_id': self._state['job_id']}

    def _run(self, mode, config, credentials, activate, resume, fee_multiplier, experiment_ref):
        previous = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            result = self.execute_fn(mode, config, self.root, credentials,
                activate=activate, resume=resume, fee_multiplier=fee_multiplier,
                experiment_ref=experiment_ref, stop_requested=self._stop.is_set,
                flatten_requested=self._flatten.is_set, progress=self._progress,
                view_progress=self._view_progress)
            fields = ('status', 'reason', 'run_id', 'summary')
            safe = {k: v for k, v in result.items() if k in fields}
            if safe.get('status') not in STATES:
                safe['status'] = 'failed'
            with self._lock:
                self._state.update(status=safe['status'], result=safe,
                                   reason=safe.get('reason'), run_id=safe.get('run_id'))
                if isinstance(safe.get('summary', {}).get('risk'), dict):
                    self._state['risk'] = safe['summary']['risk']
        except Exception:
            with self._lock:
                self._state.update(status='failed', reason='research_start_or_record_failed')
        finally:
            credentials = None
            logging.disable(previous)

    def query_contracts(self, credentials, *, continuous, start, end):
        with self._lock:
            if self.running:
                raise ValueError('请先结束当前研究任务')
            self._request_id += 1
            self._state.update(status='discovering', contracts=[],
                               request_id=self._request_id,
                               contract_request=dict(continuous=continuous,
                                                     start=str(start), end=str(end)))
            self.thread = threading.Thread(target=self._query,
                args=(credentials, continuous, start, end), daemon=True)
            self.thread.start()
            return {'ok': True, 'reason': '正在查询实际合约，请稍候。',
                    'request_id': self._request_id}

    def _query(self, credentials, continuous, start, end):
        previous = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            if self.discover_fn:
                rows = self.discover_fn(credentials=credentials, continuous=continuous,
                                         start=start, end=end)
            else:
                import tqsdk
                rows = discover_contracts(tqsdk, credentials, continuous=continuous,
                                           start=start, end=end, timeout=30)
            fields = {'symbol', 'name', 'expire_datetime', 'coverage', 'price_tick',
                      'volume_multiple', 'margin_per_lot', 'commission_per_lot'}
            safe = [{k: v for k, v in row.items() if k in fields} for row in rows]
            with self._lock:
                self._state.update(status='contracts_ready', contracts=safe, reason=None)
        except Exception:
            with self._lock:
                self._state.update(status='failed', reason='contract_query_or_permission_failed')
        finally:
            credentials = None
            logging.disable(previous)

    def stop(self, *, flatten=False):
        if type(flatten) is not bool:
            raise ValueError('停止选项无效')
        if flatten:
            if self._state.get('mode') != 'paper' or not self._state.get('activate'):
                raise ValueError('当前没有可平仓的本实验模拟控制权')
            self._flatten.set()
        else:
            self._stop.set()

    def close(self):
        if not self.running:
            return True
        if self._closing_at is None:
            self._closing_at = time.monotonic()
        self.stop()
        if time.monotonic()-self._closing_at > self._timeout+5:
            with self._lock:
                self._state.update(status='frozen', reason='shutdown_unconfirmed')
            # 仅允许本程序退出；后台未确认的状态不会标记为干净停止，重启仍须冻结。
            return True
        return False
