"""研究任务池的窄桥接；页面不能传进程、路径或任意Python入口。"""

import math
import sqlite3
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qf.backtest_plan import BacktestPlan
from qf.compute_backend import ComputeBackend
from qf.continuous_results import ContinuousReader, schema_at
from qf.local_dataset_builder import ensure_local_dataset
from qf.research_config import ResearchValidationError
from qf.research_jobs import ResearchJobs
from qf.research_live_view import LiveResearchView
from qf.research_results import run_path
from qf.research_window import ResearchWindowView


class ResearchJobsBridge:
    def __init__(self, root, experiments, *, jobs=None, login=None,
                 contract_state=None, replay=None, capacity=2, results_root=None):
        self.root = root
        self.experiments = experiments
        self._jobs = jobs
        self._jobs_args = (Path(results_root or root/'results').resolve(),
                           root/'data/workbench/backtest-jobs')
        self._jobs_capacity = capacity
        self.login = login or (lambda: None)
        self.contract_state = contract_state or (lambda: {})
        self.replay = replay
        self.live_views = {}
        self.window_views = {}

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

    def get_compute_backends(self):
        return dict(ok=True, backends=ComputeBackend.catalog())

    def start_backtest_batch(self, raw_plan, request_id=None, *, allow_partial=False):
        try:
            plan = BacktestPlan.validate(raw_plan, allow_partial=allow_partial)
        except (TypeError, ValueError) as exc:
            return self._error(str(exc) or '回测计划无效。', 'invalid_backtest_plan',
                               {'plan': str(exc) or '回测计划无效'})
        configs, refs, stress, engines, backends, datasets = [], [], [], [], [], []
        errors = {}
        for index, slot in enumerate(plan.slots, 1):
            try:
                config = self.experiments.load(slot.experiment_id, slot.revision)
                if config.strategy_version not in (2, 3):
                    errors[f'slot_{index}'] = '旧版实验只读，请复制为新版。'
                    continue
                if config.schema_version == 2:
                    state = self.contract_state() or {}
                    expected = dict(continuous=config.continuous,
                                    start=str(config.start), end=str(config.end))
                    symbols = {row['symbol'] for row in state.get('contracts', [])}
                    if (state.get('contract_request') != expected
                            or config.symbol not in symbols):
                        errors[f'slot_{index}'] = '请先查询并选择该槽位的实际合约。'
                        continue
                    row = next(row for row in state['contracts']
                               if row['symbol'] == config.symbol)
                    expiry = row.get('expire_datetime')
                    if type(expiry) in (int, float) and math.isfinite(expiry):
                        day = datetime.fromtimestamp(
                            expiry, timezone(timedelta(hours=8))).date()
                        if config.end > day:
                            errors[f'slot_{index}'] = (
                                f'{config.symbol} 不能覆盖结束日 {config.end}。')
                            continue
                configs.append(config)
                refs.append(dict(experiment_id=slot.experiment_id,
                                 revision=slot.revision))
                stress.append(slot.include_fee_stress)
                engines.append(slot.engine_kind)
                backends.append(slot.compute_backend)
                datasets.append(
                    ensure_local_dataset(self._jobs_args[0], config)
                    if slot.engine_kind == 'local_research'
                    else None
                )
            except (KeyError, TypeError, ValueError, OSError, ResearchValidationError):
                errors[f'slot_{index}'] = (
                    '快速研究缺少可复用的已核实数据。'
                    if slot.engine_kind == 'local_research'
                    else '实验修订、合约或参数无效。'
                )
        if errors:
            return self._error('批量回测未启动：请核对标记槽位。',
                               'batch_validation_failed', errors)
        credentials = self.login() if 'tqsdk_validation' in engines else ('', '')
        if not credentials and 'tqsdk_validation' in engines:
            return self._error('请先保存快期凭证。', 'credentials_required')
        previous = self.jobs.capacity
        try:
            self.jobs.set_capacity(plan.capacity)
            result = self.jobs.submit_many(
                configs, credentials=credentials, experiment_refs=refs,
                include_fee_stress=stress,
                engine_kinds=engines,
                compute_backends=backends,
                dataset_ids=datasets,
                request_id=request_id,
            )
            return dict(ok=True, reason=f'已提交{len(plan.slots)}个回测槽位。',
                        capacity=plan.capacity, **result)
        except (KeyError, TypeError, ValueError, OSError):
            try:
                self.jobs.set_capacity(previous)
            except ValueError:
                pass
            return self._error('批量回测未提交：任务池拒绝本次计划。',
                               'batch_submit_failed')

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

    def remove_backtest(self, job_id):
        try:
            self.jobs.remove(job_id)
            self._close_live(job_id)
            self._close_window(job_id)
            return dict(ok=True, reason='任务卡已移除；保存的结果文件未删除。')
        except KeyError:
            return self._error('任务不存在。', 'job_not_found')
        except ValueError:
            return self._error('运行中的任务需先停止，再移除。', 'job_running')

    def set_backtest_watch(self, job_id, enabled):
        if type(enabled) is not bool:
            return self._error('观看参数无效。', 'invalid_watch')
        try:
            self.jobs.set_watch(job_id, enabled)
            return dict(ok=True, reason='观看状态已更新。')
        except (KeyError, OSError):
            return self._error('任务不可观看。', 'job_not_watchable')

    def _close_live(self, job_id):
        view = self.live_views.pop(job_id, None)
        if view is not None:
            try:
                view.close()
            except (OSError, ValueError):
                pass

    def _close_window(self, job_id):
        view = self.window_views.pop(job_id, None)
        if view is not None:
            try:
                view.close()
            except (OSError, ValueError):
                pass

    def _ledger(self, job_id):
        state = self.jobs.snapshot(job_id)
        run_id = state.get('run_id')
        if not run_id:
            return dict(
                available=False, trades=[], fills=[], reconciled=False,
                truncated=False, reason='该任务尚未生成成交账本。')
        root = self._jobs_args[0]
        path = run_path(root, run_id)
        schema = schema_at(path)
        if schema == 2:
            return ContinuousReader(path).trade_ledger()
        if schema == 3:
            from qf.local_results import local_trade_ledger
            with sqlite3.connect(
                (path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True
            ) as db:
                return local_trade_ledger(db)
        return dict(
            available=False, trades=[], fills=[], reconciled=False,
            truncated=False, reason='固定月份旧实验没有逻辑交易账本。')

    def get_trade_ledger(self, job_id):
        try:
            return dict(ok=True, ledger=self._ledger(job_id))
        except (KeyError, ValueError, OSError, sqlite3.Error):
            return self._error('逐笔交易账本暂不可用；后台计算不受影响。',
                               'trade_ledger_unavailable')

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
            live = self.live_views.get(job_id)
            if live is None:
                live = LiveResearchView(
                    lambda: self.jobs.live_snapshot(job_id),
                    state_provider=lambda: self.jobs.snapshot(job_id))
                self.live_views[job_id] = live
            return dict(ok=True, url=live.open(), run_id=state.get('run_id'),
                        generation=live.generation, mode='live')
        except (KeyError, ValueError, OSError):
            return self._error('运行图不可用，请核对任务状态。', 'chart_unavailable')

    def open_research_window(self, job_id):
        try:
            view = self.window_views.get(job_id)
            if view is None:
                def chart_url():
                    result = self.open_backtest_chart(job_id)
                    if not result.get('ok'):
                        raise ValueError(result.get('reason') or '运行图不可用')
                    return result['url']

                view = ResearchWindowView(
                    job_id,
                    lambda: self.jobs.snapshot(job_id),
                    lambda: self._ledger(job_id),
                    chart_url,
                )
                self.window_views[job_id] = view
            return dict(ok=True, url=view.open(), job_id=job_id)
        except (KeyError, OSError, TypeError, ValueError):
            return self._error('完整研究窗口不可用，请核对任务状态。',
                               'research_window_unavailable')

    def open_backtest_window(self, job_id):
        result = self.open_research_window(job_id)
        if not result.get('ok'):
            return result
        try:
            opened = webbrowser.open_new(result['url'])
        except (OSError, webbrowser.Error):
            return self._error('独立图表窗口未能打开，请允许浏览器访问本机图表。',
                               'chart_window_failed')
        if not opened:
            return self._error('未能启动本机浏览器；请检查默认浏览器设置。',
                               'chart_window_failed')
        return result | dict(
            reason='已在独立浏览器窗口打开完整研究观察窗；关闭主工作台后实时更新停止。')

    def set_backtest_capacity(self, value):
        try:
            self.jobs.set_capacity(value)
            return dict(ok=True, capacity=self.jobs.capacity)
        except ValueError:
            return self._error('并发数必须为1—4。', 'invalid_capacity')

    def close(self):
        for job_id in list(self.live_views):
            self._close_live(job_id)
        for job_id in list(self.window_views):
            self._close_window(job_id)
        return True if self._jobs is None else self._jobs.close()
