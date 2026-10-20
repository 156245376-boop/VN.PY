import time
from dataclasses import replace

import pytest
from research_worker_probe import launch, launch_controlled
from test_continuous_runtime import config
from test_local_dataset_builder import build_local_dataset_from_validation, write_validation
from test_local_dataset_builder import config as local_config

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


def test_submit_many_is_atomic_when_any_config_is_invalid(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=2,
                        worker_target=launch)
    try:
        valid = config()
        invalid = replace(valid, bar_seconds=0)
        try:
            jobs.submit_many(
                [valid, invalid], credentials=('u', 'p'),
                experiment_refs=[{'experiment_id': 'a', 'revision': 1},
                                 {'experiment_id': 'b', 'revision': 1}],
                include_fee_stress=[False, False],
                request_id='batch-failed')
        except ValueError:
            pass
        else:
            raise AssertionError('invalid batch must fail')
        assert jobs.list() == []
    finally:
        assert jobs.close()


def test_submit_many_keeps_slot_order_and_request_idempotency(tmp_path):
    jobs = ResearchJobs(tmp_path/'results', tmp_path/'jobs', capacity=2,
                        worker_target=launch)
    try:
        configs = [config(), config(), config()]
        refs = [{'experiment_id': 'a', 'revision': 1},
                {'experiment_id': 'b', 'revision': 1},
                {'experiment_id': 'c', 'revision': 1}]
        first = jobs.submit_many(
            configs, credentials=('u', 'p'), experiment_refs=refs,
            include_fee_stress=[False, True, False], request_id='batch-same')
        assert len(first['groups']) == 3
        assert [len(group) for group in first['groups']] == [1, 2, 1]
        assert first['job_ids'] == [job_id for group in first['groups']
                                    for job_id in group]
        again = jobs.submit_many(
            configs, credentials=('u', 'p'), experiment_refs=refs,
            include_fee_stress=[False, True, False], request_id='batch-same')
        assert again['job_ids'] == first['job_ids']
        for job_id in first['job_ids']:
            assert wait(jobs, job_id, timeout=8)['status'] == 'backtest_finished'
    finally:
        assert jobs.close()


def test_local_job_uses_frozen_dataset_without_account_connection(tmp_path):
    results = tmp_path/'results'
    cfg, validation_id = write_validation(results)
    dataset_id, _dataset = build_local_dataset_from_validation(
        results, validation_id, cfg
    )
    jobs = ResearchJobs(
        results,
        tmp_path/'jobs',
        capacity=1,
        worker_target=launch,
    )
    try:
        submitted = jobs.submit(
            local_config(),
            credentials=('', ''),
            experiment_ref={'experiment_id': 'local', 'revision': 1},
            engine_kind='local_research',
            compute_backend='cpu',
            dataset_id=dataset_id,
        )
        state = wait(jobs, submitted['selected_job_id'], timeout=10)
        assert state['status'] == 'backtest_finished'
        assert state['engine_kind'] == 'local_research'
        assert state['dataset_id'] == dataset_id
    finally:
        assert jobs.close()
