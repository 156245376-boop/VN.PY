import threading
import time

from test_indicator_calculation import bars, request

from qf.indicator_catalog import default_item
from qf.indicator_jobs import IndicatorJobs


def job(pane='pane-1', revision=1):
    rows = bars(5)
    return request(rows, [default_item('ma')]) | dict(pane_id=pane, generation=1,
        chart_revision=1, settings_revision=revision, data_revision='data-1', request_id=revision,
        coverage_end_ns=str(int(rows[-1]['time_ns'])+60_000_000_000))


def wait_for(jobs, ids):
    end = time.monotonic()+3
    while time.monotonic() < end:
        values = jobs.poll(ids)
        if all(v['status'] not in ('queued', 'running') for v in values.values()):
            return values
        time.sleep(.01)
    raise AssertionError('指标任务未完成')


def test_one_worker_latest_pending_per_pane():
    started, release = threading.Event(), threading.Event()
    active = maximum = 0
    observed = []

    def compute(data):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        observed.append(data['settings_revision'])
        started.set()
        release.wait(2)
        active -= 1
        return {'series': []}

    jobs = IndicatorJobs(compute=compute)
    try:
        first = jobs.submit(job())['job_id']
        assert started.wait(1)
        old = jobs.submit(job(revision=2))['job_id']
        other = jobs.submit(job('pane-2', 4))['job_id']
        new = jobs.submit(job(revision=3))['job_id']
        release.set()
        states = wait_for(jobs, [first, old, other, new])
        assert maximum == 1
        assert states[old]['status'] == 'superseded'
        assert observed == [1, 4, 3]
        assert states[other]['identity']['pane_id'] == 'pane-2'
        assert states[new]['identity']['settings_revision'] == 3
    finally:
        release.set()
        jobs.close()


def test_close_discards_pending_and_rejects_new_jobs():
    jobs = IndicatorJobs()
    jobs.close()
    assert jobs.submit(job())['ok'] is False
    assert jobs.submit(job() | {'token': 'private'})['ok'] is False
    broken = job()
    broken['rows'][0]['close'] = float('inf')
    assert jobs.submit(broken)['ok'] is False
