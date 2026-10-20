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


def launch(task, credential_pipe, control_pipe, status_queue, frame_queue,
           terminal_pipe, stop_event, results_root):
    worker_main(task, credential_pipe, control_pipe, status_queue, frame_queue,
                terminal_pipe, stop_event, results_root=results_root,
                execute_fn=fake_execute)
