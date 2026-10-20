"""回测任务池：父进程只管理身份、槽位和控制通道。"""

import multiprocessing
import queue
import time
from pathlib import Path

from qf.journal import PaperLock
from qf.research_protocol import accept_message, freeze_backtest
from qf.research_worker import worker_main


def _safe_state(job):
    return {key: value for key, value in job.items()
            if key not in {'process', 'control', 'terminal', 'stop', 'credentials',
                           'parent_credential', 'status_queue', 'frame_queue', 'parent_terminal'}}


class ResearchJobs:
    def __init__(self, results_root, jobs_root, *, capacity=2, worker_target=None,
                 context=None):
        self.results_root = Path(results_root)
        self.jobs_root = Path(jobs_root)
        self.capacity = self._capacity(capacity)
        self.context = context or multiprocessing.get_context('spawn')
        self.worker_target = worker_target or worker_main
        self.jobs, self.order, self.request_jobs = {}, [], {}
        self._credentials = None
        self._lock = PaperLock(self.jobs_root)
        self._lock.__enter__()
        self._closed = False

    @staticmethod
    def _capacity(value):
        if type(value) is not int or not 1 <= value <= 4:
            raise ValueError('并发数必须为1—4')
        return value

    def submit(self, config, *, credentials, experiment_ref=None,
               include_fee_stress=False, request_id=None):
        if self._closed:
            raise ValueError('任务池已关闭')
        if request_id is not None and request_id in self.request_jobs:
            ids = self.request_jobs[request_id]
            return dict(job_ids=ids, selected_job_id=ids[0])
        import uuid
        job_id = uuid.uuid4().hex
        task = freeze_backtest(config, experiment_ref, job_id=job_id)
        job = dict(job_id=job_id, epoch=task.epoch, run_id=None, status='waiting',
                   running=False, config=task.config, experiment_ref=task.experiment_ref,
                   fee_multiplier=1, parent_job_id=None, progress=None, account=None,
                   risk={}, reason='capacity', task=task)
        self.jobs[job_id] = job
        self.order.append(job_id)
        ids = [job_id]
        if include_fee_stress:
            stress_id = uuid.uuid4().hex
            stress_task = freeze_backtest(config, experiment_ref, job_id=stress_id,
                                           fee_multiplier=2)
            self.jobs[stress_id] = dict(job_id=stress_id, epoch=stress_task.epoch,
                run_id=None, status='waiting', running=False, config=stress_task.config,
                experiment_ref=stress_task.experiment_ref, fee_multiplier=2,
                parent_job_id=job_id, progress=None, account=None, risk={},
                reason='baseline_pending', task=stress_task)
            self.order.append(stress_id)
            ids.append(stress_id)
        if request_id is not None:
            self.request_jobs[request_id] = ids
        self._credentials = tuple(credentials)
        self._start_available(credentials)
        return dict(job_ids=ids, selected_job_id=job_id)

    def _start_available(self, credentials):
        active = sum(1 for job in self.jobs.values() if job['running'])
        for job_id in self.order:
            if active >= self.capacity:
                break
            job = self.jobs[job_id]
            if job['running'] or job['status'] not in ('waiting',):
                continue
            if job['parent_job_id'] and self.jobs[job['parent_job_id']]['status'] not in (
                    'backtest_finished',):
                continue
            self._start(job, credentials)
            active += 1
            job['status'], job['reason'] = 'starting', None

    def _start(self, job, credentials):
        credential_recv, credential_send = self.context.Pipe(False)
        control_recv, control_send = self.context.Pipe(False)
        status = self.context.Queue(maxsize=1)
        frames = self.context.Queue(maxsize=1)
        terminal_recv, terminal_send = self.context.Pipe(False)
        stop = self.context.Event()
        credential_send.send(tuple(credentials))
        credential_send.close()
        process = self.context.Process(target=self.worker_target, args=(
            job['task'], credential_recv, control_recv, status, frames,
            terminal_send, stop, str(self.results_root)))
        process.start()
        job.update(running=True, process=process, status_queue=status,
                   frame_queue=frames, control=control_send, terminal=terminal_recv,
                   stop=stop, last_seq={}, bound_run_id=None)

    def _drain_one(self, job):
        status_queue, frames = job.get('status_queue'), job.get('frame_queue')
        if status_queue is not None:
            try:
                raw = status_queue.get_nowait()
                accepted = accept_message(job['task'], raw, last_seq=job['last_seq'],
                                           bound_run_id=job['bound_run_id'])
                if accepted:
                    job['last_seq']['status'] = raw['seq']
                    job['run_id'] = raw['run_id'] or job['run_id']
                    job['bound_run_id'] = job['bound_run_id'] or raw['run_id']
                    payload = accepted['payload']
                    job['progress'] = payload.get('details') or job['progress']
                    job['account'] = payload.get('account') or job['account']
                    job['risk'] = payload.get('risk') or job['risk']
                    if job['status'] in ('starting', 'waiting'):
                        job['status'] = 'active'
            except queue.Empty:
                pass
        if frames is not None:
            try:
                raw = frames.get_nowait()
                if accept_message(job['task'], raw, last_seq=job['last_seq'],
                                  bound_run_id=job['bound_run_id']):
                    job['last_seq']['frame'] = raw['seq']
                    job['frame'] = raw['payload']
            except queue.Empty:
                pass
        terminal = job.get('terminal')
        if terminal is not None and terminal.poll():
            raw = terminal.recv()
            if accept_message(job['task'], raw, last_seq=job['last_seq'],
                              bound_run_id=job['bound_run_id']):
                job['last_seq']['terminal'] = raw['seq']
                payload = raw['payload']
                job.update(status=payload.get('status', 'failed'), running=False,
                           reason=payload.get('reason'), run_id=payload.get('run_id'),
                           result={key: value for key, value in payload.items()
                                   if key in ('status', 'reason', 'run_id',
                                              'failure_context', 'summary')})
                job['bound_run_id'] = job['bound_run_id'] or payload.get('run_id')
                try:
                    job['terminal'].close()
                except Exception:
                    pass
                job['terminal'] = None

    def _drain_all(self):
        for job in self.jobs.values():
            if job.get('running') or job.get('terminal') is not None:
                self._drain_one(job)
            if not job.get('running') and job.get('terminal'):
                # terminal pipe can arrive after process exit; keep polling next tick
                pass
        if not self._closed and self._credentials is not None:
            self._start_available(self._credentials)
    def list(self):
        self._drain_all()
        return [_safe_state({key: value for key, value in job.items()
                             if key not in {'task', 'frame', 'result'}})
                for job in self.jobs.values()]

    def snapshot(self, job_id):
        if job_id not in self.jobs:
            raise KeyError('任务不存在')
        self._drain_one(self.jobs[job_id])
        if not self._closed and self._credentials is not None:
            self._start_available(self._credentials)
        return _safe_state({key: value for key, value in self.jobs[job_id].items()
                            if key not in {'task', 'frame', 'result'}})

    def live_snapshot(self, job_id):
        return self.jobs.get(job_id, {}).get('frame')

    def stop(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError('任务不存在')
        if job.get('running'):
            job['status'] = 'stopping'
            try:
                job['stop'].set()
                job['control'].close()
            except Exception:
                pass

    def set_watch(self, job_id, enabled):
        if job_id is None:
            for job in self.jobs.values():
                if job.get('control'):
                    try:
                        job['control'].send(dict(kind='set_watch', enabled=False,
                                                 view_generation=0))
                    except Exception:
                        pass
            return
        job = self.jobs.get(job_id)
        if job is None or job.get('control') is None:
            raise KeyError('任务不可观看')
        generation = int(time.monotonic()*1000)
        job['control'].send(dict(kind='set_watch', enabled=bool(enabled),
                                 view_generation=generation))

    def set_capacity(self, value):
        self.capacity = self._capacity(value)
        if self.jobs and self._credentials is not None:
            self._start_available(self._credentials)

    def close(self):
        if self._closed:
            return True
        self._closed = True
        deadline = time.monotonic()+5
        for job in self.jobs.values():
            if job.get('running'):
                try:
                    job['stop'].set()
                    job['control'].close()
                except Exception:
                    pass
        for job in self.jobs.values():
            process = job.get('process')
            if process is not None:
                process.join(max(0, deadline-time.monotonic()))
                if process.is_alive():
                    process.terminate()
                    process.join(1)
        try:
            self._lock.__exit__(None, None, None)
        except Exception:
            pass
        return all(not job.get('process') or not job['process'].is_alive()
                   for job in self.jobs.values())
