"""无账户的spawn验收执行器；只验证进程、协议和重叠时间。"""

import os
import time
import uuid

from qf.research_worker import worker_main


def fake_execute(mode, config, root, credentials, **kwargs):
    progress = kwargs.get('progress')
    view = kwargs.get('view_progress')
    wants = kwargs.get('view_requested') or (lambda: False)
    run_id = 'run-'+uuid.uuid4().hex[:12]
    progress('connecting', run_id=run_id)
    started = time.monotonic()
    if wants() and view:
        view({'run_id': run_id, 'revision': 1, 'as_of_ns': '1', 'bars': [],
              'fills': [], 'risk_events': [], 'ma_series': []})
    time.sleep(.6)
    return {'status': 'backtest_finished', 'reason': 'historical_replay_completed',
            'run_id': run_id, 'failure_context': {},
            'summary': {'fill_count': 1, 'started': started,
                        'ended': time.monotonic(), 'pid': os.getpid()}}


def controlled_execute(mode, config, root, credentials, **kwargs):
    progress = kwargs.get('progress')
    run_id = 'run-'+uuid.uuid4().hex[:12]
    ref = kwargs.get('experiment_ref') or {}
    progress('research_progress', details={
        'stage': 'backtesting', 'percent': 10, 'completed_bars': 2,
        'fill_count': 0, 'elapsed_seconds': .1, 'last_advance_age_seconds': 0,
        'current_ns': '1'})
    progress('research_state', run_id=run_id, risk={'quantity': 1},
             account={'equity': '100000'})
    if ref.get('experiment_id') == 'hold':
        deadline = time.monotonic()+4
        while not kwargs['stop_requested']() and time.monotonic() < deadline:
            time.sleep(.02)
        if time.monotonic() >= deadline:
            return {'status': 'failed', 'reason': 'stop_signal_missing',
                    'run_id': run_id, 'failure_context': {}}
        return {'status': 'stopped', 'reason': 'requested_stop',
                'run_id': run_id, 'failure_context': {}}
    time.sleep(.1)
    return {'status': 'backtest_finished', 'reason': 'historical_replay_completed',
            'run_id': run_id, 'failure_context': {}}


def launch(task, credential_pipe, control_pipe, status_queue, frame_queue,
           terminal_pipe, stop_event, results_root):
    worker_main(task, credential_pipe, control_pipe, status_queue, frame_queue,
                terminal_pipe, stop_event, results_root=results_root,
                execute_fn=fake_execute)


def launch_controlled(task, credential_pipe, control_pipe, status_queue, frame_queue,
                      terminal_pipe, stop_event, results_root):
    worker_main(task, credential_pipe, control_pipe, status_queue, frame_queue,
                terminal_pipe, stop_event, results_root=results_root,
                execute_fn=controlled_execute)
