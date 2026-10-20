import multiprocessing

from research_worker_probe import launch
from test_continuous_runtime import config

from qf.research_protocol import accept_message, freeze_backtest
from qf.research_view import ViewDemand


def test_protocol_rejects_wrong_epoch_and_duplicate_sequence():
    task = freeze_backtest(config(), {'experiment_id': 'e', 'revision': 1})
    raw = {'job_id': task.job_id, 'epoch': task.epoch, 'run_id': None,
           'stream': 'status', 'seq': 1, 'kind': 'state', 'payload': {}}
    last = {}
    assert accept_message(task, raw, last_seq=last) == raw
    last['status'] = 1
    assert accept_message(task, raw, last_seq=last) is None
    assert accept_message(task, raw | {'epoch': 'b'*32}, last_seq={}) is None


def test_two_workers_overlap_with_distinct_pids(tmp_path):
    context = multiprocessing.get_context('spawn')
    tasks = [freeze_backtest(config(), {'experiment_id': str(i), 'revision': 1})
             for i in range(2)]
    processes, terminals = [], []
    for task in tasks:
        recv_credential, send_credential = context.Pipe(False)
        recv_control, send_control = context.Pipe(False)
        status, frames = context.Queue(maxsize=1), context.Queue(maxsize=1)
        recv_terminal, send_terminal = context.Pipe(False)
        stop = context.Event()
        send_credential.send(('offline', 'private-password'))
        send_credential.close()
        process = context.Process(target=launch, args=(
            task, recv_credential, recv_control, status, frames,
            send_terminal, stop, str(tmp_path)))
        process.start()
        processes.append((process, send_control, recv_terminal, stop))
        terminals.append(recv_terminal)
    for process, send_control, _recv_terminal, _stop in processes:
        send_control.close()
        process.join(5)
        assert process.exitcode == 0
    results = [recv.recv() for recv in terminals]
    assert all(item['payload']['status'] == 'backtest_finished' for item in results)
    first, second = [item['payload']['summary'] for item in results]
    assert first['pid'] != second['pid']
    assert first['started'] < second['ended'] and second['started'] < first['ended']
    assert ('private-password' not in str(results))


def test_view_demand_defaults_off_and_switches():
    demand = ViewDemand()
    assert not demand.wants_frame()
    demand.set(True, 2)
    assert demand.wants_frame()
    demand.set(False, 3)
    assert not demand.wants_frame()
