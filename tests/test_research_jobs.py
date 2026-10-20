import time

from research_worker_probe import launch
from test_continuous_runtime import config

from qf.research_jobs import ResearchJobs


def wait(jobs, job_id, timeout=5):
    end = time.time()+timeout
    while time.time() < end:
        state = jobs.snapshot(job_id)
        if not state['running'] and state['status'] in (
                'backtest_finished', 'failed', 'stopped', 'frozen'):
            return state
        time.sleep(.05)
    raise AssertionError(jobs.snapshot(job_id))


def test_capacity_and_independent_jobs(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=2,
                        worker_target=launch)
    try:
        first = jobs.submit(config(), credentials=('u', 'p'),
                            experiment_ref={'experiment_id': 'a', 'revision': 1},
                            request_id='same')
        assert jobs.submit(config(), credentials=('u', 'p'),
                           experiment_ref={'experiment_id': 'a', 'revision': 1},
                           request_id='same')['job_ids'] == first['job_ids']
        second = jobs.submit(config(), credentials=('u', 'p'),
                             experiment_ref={'experiment_id': 'b', 'revision': 1})
        third = jobs.submit(config(), credentials=('u', 'p'),
                            experiment_ref={'experiment_id': 'c', 'revision': 1})
        states = jobs.list()
        assert sum(item['running'] for item in states) == 2
        assert jobs.snapshot(third['selected_job_id'])['status'] == 'waiting'
        assert wait(jobs, first['selected_job_id'])['status'] == 'backtest_finished'
        assert wait(jobs, second['selected_job_id'])['status'] == 'backtest_finished'
        assert wait(jobs, third['selected_job_id'])['status'] == 'backtest_finished'
        assert 'private-password' not in str(states)
    finally:
        assert jobs.close()


def test_capacity_validation():
    for value in (0, 5, True):
        try:
            ResearchJobs('.', '.', capacity=value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
