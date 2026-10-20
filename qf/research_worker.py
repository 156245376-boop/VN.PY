"""子进程入口；只接收冻结任务和私有凭证，不接收父进程SDK对象。"""

import queue
import threading

from qf.research_config import validate_research_config
from qf.research_protocol import message
from qf.research_runtime import execute_research
from qf.research_view import ViewDemand


def _put_latest(target, value):
    try:
        target.put_nowait(value)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(value)
        except queue.Full:
            pass


def worker_main(task, credential_pipe, control_pipe, status_queue, frame_queue,
                terminal_pipe, stop_event, results_root, *, execute_fn=None):
    demand = ViewDemand()
    safe = {'status', 'reason', 'run_id', 'failure_context', 'summary'}
    last_run = [None]
    sequences = {'status': 0, 'frame': 0}

    def control_loop():
        while not stop_event.is_set():
            try:
                raw = control_pipe.recv()
            except (EOFError, OSError):
                stop_event.set()
                return
            if not isinstance(raw, dict) or raw.get('kind') != 'set_watch':
                continue
            try:
                demand.set(bool(raw['enabled']), int(raw['view_generation']))
            except (KeyError, TypeError, ValueError):
                continue

    credentials = None
    try:
        credentials = credential_pipe.recv()
        credential_pipe.close()
        if not isinstance(credentials, tuple) or len(credentials) != 2:
            raise ValueError('credentials')
        thread = threading.Thread(target=control_loop, daemon=True)
        thread.start()

        def progress(stage, **fields):
            run_id = fields.get('run_id') or last_run[0]
            if run_id:
                last_run[0] = run_id
            sequences['status'] += 1
            payload = {'stage': stage, **{key: value for key, value in fields.items()
                                          if key in safe or key in {
                                              'details', 'equity', 'commission', 'symbol',
                                              'phase', 'risk', 'logical_risk', 'roll',
                                              'account'}}}
            _put_latest(status_queue, message(task, run_id=run_id, stream='status',
                seq=sequences['status'], kind='state', payload=payload))

        def view(frame):
            if not demand.wants_frame():
                return
            sequences['frame'] += 1
            _put_latest(frame_queue, message(task, run_id=last_run[0], stream='frame',
                seq=sequences['frame'], kind='frame', payload=frame))

        runner = execute_fn or execute_research
        result = runner('backtest', validate_research_config(task.config),
                        results_root, credentials,
                        progress=progress, view_progress=view,
                        view_requested=demand.wants_frame,
                        experiment_ref=task.experiment_ref,
                        fee_multiplier=task.fee_multiplier,
                        job_binding={'job_id': task.job_id, 'epoch': task.epoch})
    except Exception:
        result = {'status': 'failed', 'reason': 'research_start_or_record_failed',
                  'run_id': last_run[0], 'failure_context': {}}
    finally:
        credentials = None
        try:
            credential_pipe.close()
        except Exception:
            pass
    safe_result = {key: result[key] for key in ('status', 'reason', 'run_id',
                                                 'failure_context', 'summary')
                   if key in result}
    sequences['terminal'] = 1
    terminal_pipe.send(message(task, run_id=safe_result.get('run_id'),
        stream='terminal', seq=1, kind='result', payload=safe_result))
    terminal_pipe.close()
    stop_event.set()
