"""研究任务池的窄桥接；页面不能传进程、路径或任意Python入口。"""

import math
from datetime import datetime, timedelta, timezone

from qf.research_config import ResearchValidationError
from qf.research_jobs import ResearchJobs
from qf.research_live_view import LiveResearchView


class ResearchJobsBridge:
    def __init__(self, root, experiments, *, jobs=None, login=None,
                 contract_state=None, replay=None, capacity=2):
        self.root = root
        self.experiments = experiments
        self._jobs = jobs
        self._jobs_args = (root/'results', root/'data/workbench/backtest-jobs')
        self._jobs_capacity = capacity
        self.login = login or (lambda: None)
        self.contract_state = contract_state or (lambda: {})
        self.replay = replay
        self.live = None
        self.live_job = None

    @property
    def jobs(self):
        if self._jobs is None:
            self._jobs = ResearchJobs(*self._jobs_args, capacity=self._jobs_capacity)
        return self._jobs

    def _error(self, reason, code='research_job_failed', field_errors=None):
        return dict(ok=False, reason=reason, code=code, field_errors=field_errors or {})

    def start_backtest(self, experiment_id, revision, include_fee_stress=False,
                       request_id=None):
        try:
            config = self.experiments.load(experiment_id, revision)
            if config.strategy_version not in (2, 3):
                return self._error('旧版实验只读，请复制为新版后运行。', 'legacy_read_only')
            if config.schema_version == 2:
                state = self.contract_state() or {}
                expected = dict(continuous=config.continuous,
                                start=str(config.start), end=str(config.end))
                symbols = {row['symbol'] for row in state.get('contracts', [])}
                if (state.get('contract_request') != expected
                        or config.symbol not in symbols):
                    return self._error('请先查询并选择当前区间的实际合约。',
                        'contract_required')
                row = next(row for row in state['contracts'] if row['symbol'] == config.symbol)
                expiry = row.get('expire_datetime')
                if type(expiry) in (int, float) and math.isfinite(expiry):
                    day = datetime.fromtimestamp(expiry, timezone(timedelta(hours=8))).date()
                    if config.end > day:
                        return self._error(f'合约 {config.symbol} 不能覆盖结束日 {config.end}。',
                            'contract_range_exceeds_expiry')
            credentials = self.login()
            if not credentials:
                return self._error('请先保存快期凭证。', 'credentials_required')
            ref = dict(experiment_id=experiment_id, revision=revision)
            result = self.jobs.submit(config, credentials=credentials,
                                      experiment_ref=ref,
                                      include_fee_stress=include_fee_stress,
                                      request_id=request_id)
            return dict(ok=True, reason='回测任务已提交。', **result)
        except (ValueError, KeyError, TypeError, OSError, ResearchValidationError):
            return self._error('回测未提交：请核对实验修订、凭证和当前账户。')

    def list_backtest_jobs(self):
        return dict(ok=True, jobs=self.jobs.list())

    def get_backtest_state(self, job_id):
        try:
            return dict(ok=True, state=self.jobs.snapshot(job_id))
        except KeyError:
            return self._error('任务不存在。', 'job_not_found')

    def stop_backtest(self, job_id):
        try:
            self.jobs.stop(job_id)
            return dict(ok=True, reason='正在停止该任务；停止不代表平仓。')
        except KeyError:
            return self._error('任务不存在。', 'job_not_found')

    def set_backtest_watch(self, job_id, enabled):
        if type(enabled) is not bool:
            return self._error('观看参数无效。', 'invalid_watch')
        try:
            self.jobs.set_watch(job_id, enabled)
            return dict(ok=True, reason='观看状态已更新。')
        except (KeyError, OSError):
            return self._error('任务不可观看。', 'job_not_watchable')

    def open_backtest_chart(self, job_id):
        try:
            state = self.jobs.snapshot(job_id)
            self.jobs.set_watch(job_id, True)
            if state.get('run_id') and not self.jobs.live_snapshot(job_id):
                if self.replay is not None:
                    url = self.replay.open(state['run_id'])
                    return dict(ok=True, url=url, run_id=state['run_id'],
                                revision=self.replay.revision, mode='replay')
                return self._error('该任务没有可显示的结果。', 'replay_unavailable')
            if self.live is None or self.live_job != job_id:
                self.live = LiveResearchView(
                    lambda: self.jobs.live_snapshot(job_id),
                    state_provider=lambda: self.jobs.snapshot(job_id))
                self.live_job = job_id
            return dict(ok=True, url=self.live.open(), run_id=state.get('run_id'),
                        generation=self.live.generation, mode='live')
        except (KeyError, ValueError, OSError):
            return self._error('运行图不可用，请核对任务状态。', 'chart_unavailable')

    def set_backtest_capacity(self, value):
        try:
            self.jobs.set_capacity(value)
            return dict(ok=True, capacity=self.jobs.capacity)
        except ValueError:
            return self._error('并发数必须为1—4。', 'invalid_capacity')

    def close(self):
        if self.live is not None:
            try:
                self.live.close()
            except Exception:
                pass
        return True if self._jobs is None else self._jobs.close()
