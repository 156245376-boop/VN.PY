import time

import pytest
from research_worker_probe import launch, launch_controlled
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


def wait_running(jobs, job_id, timeout=5):
    end = time.time()+timeout
    while time.time() < end:
        state = jobs.snapshot(job_id)
        if state['running'] and state['status'] == 'active':
            return state
        time.sleep(.05)
    raise AssertionError(jobs.snapshot(job_id))


def test_stop_reaches_worker_and_releases_capacity(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=1,
                        worker_target=launch_controlled)
    try:
        first = jobs.submit(config(), credentials=('u', 'p'),
                            experiment_ref={'experiment_id': 'hold', 'revision': 1})
        waiting = jobs.submit(config(), credentials=('u', 'p'),
                              experiment_ref={'experiment_id': 'next', 'revision': 1})
        active = wait_running(jobs, first['selected_job_id'])
        assert active['progress']['percent'] == 10
        assert active['account'] == {'equity': '100000'}
        assert jobs.snapshot(waiting['selected_job_id'])['status'] == 'waiting'
        jobs.stop(first['selected_job_id'])
        stopped = wait(jobs, first['selected_job_id'])
        assert stopped['status'] == 'stopped'
        assert stopped['reason'] == 'requested_stop'
        assert wait(jobs, waiting['selected_job_id'])['status'] == 'backtest_finished'
    finally:
        assert jobs.close()


def test_waiting_job_can_be_removed_without_starting(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=1,
                        worker_target=launch_controlled)
    try:
        first = jobs.submit(config(), credentials=('u', 'p'),
                            experiment_ref={'experiment_id': 'hold', 'revision': 1})
        extra = jobs.submit(config(), credentials=('u', 'p'),
                            experiment_ref={'experiment_id': 'extra', 'revision': 1})
        wait_running(jobs, first['selected_job_id'])
        with pytest.raises(ValueError):
            jobs.remove(first['selected_job_id'])
        extra_id = extra['selected_job_id']
        assert jobs.snapshot(extra_id)['status'] == 'waiting'
        jobs.remove(extra_id)
        assert extra_id not in {job['job_id'] for job in jobs.list()}
        try:
            jobs.snapshot(extra_id)
        except KeyError:
            pass
        else:
            raise AssertionError('removed job still exists')
        jobs.stop(first['selected_job_id'])
        assert wait(jobs, first['selected_job_id'])['status'] == 'stopped'
    finally:
        assert jobs.close()


def test_finished_job_records_watch_without_writing_to_dead_worker(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=1,
                        worker_target=launch)
    try:
        submitted = jobs.submit(config(), credentials=('u', 'p'),
                                experiment_ref={'experiment_id': 'done', 'revision': 1})
        job_id = submitted['selected_job_id']
        assert wait(jobs, job_id)['status'] == 'backtest_finished'
        jobs.set_watch(job_id, True)
        assert jobs.snapshot(job_id)['watch'] is True
    finally:
        assert jobs.close()
