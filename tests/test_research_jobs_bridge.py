from test_continuous_config import continuous_data

from qf.experiment_store import ExperimentStore
from qf.research_config import validate_research_config
from qf.research_jobs_bridge import ResearchJobsBridge


class FakeJobs:
    def __init__(self):
        self.capacity = 2
        self.submitted = []
        self.items = {}
        self.watch = []

    def submit(self, config, **kwargs):
        job_id = 'a'*32
        self.items[job_id] = {'job_id': job_id, 'status': 'waiting', 'running': False}
        self.submitted.append((config, kwargs))
        return {'job_ids': [job_id], 'selected_job_id': job_id}

    def list(self):
        return list(self.items.values())

    def snapshot(self, job_id):
        if job_id not in self.items:
            raise KeyError(job_id)
        return self.items[job_id]

    def stop(self, job_id):
        if job_id not in self.items:
            raise KeyError(job_id)
        self.items[job_id]['status'] = 'stopping'

    def set_watch(self, job_id, enabled):
        if job_id not in self.items:
            raise KeyError(job_id)
        self.watch.append((job_id, enabled))

    def live_snapshot(self, job_id):
        return None

    def set_capacity(self, value):
        if value not in (1, 2, 3, 4):
            raise ValueError()
        self.capacity = value

    def close(self):
        return True


def bridge(tmp_path, jobs=None):
    config = validate_research_config(continuous_data())
    store = ExperimentStore(tmp_path/'experiments')
    ref = store.save(config)
    jobs = jobs or FakeJobs()
    value = ResearchJobsBridge(tmp_path, store, jobs=jobs, login=lambda: ('u', 'p'))
    return value, ref, jobs


def test_continuous_experiment_submits_without_month_query(tmp_path):
    value, ref, jobs = bridge(tmp_path)
    response = value.start_backtest(ref['experiment_id'], ref['revision'],
                                     request_id='request-1')
    assert response['ok'] and response['job_ids'] == ['a'*32]
    assert len(jobs.submitted) == 1
    assert jobs.submitted[0][0].schema_version == 3
    assert value.list_backtest_jobs()['ok']
    assert value.get_backtest_state('a'*32)['ok']
    assert value.stop_backtest('a'*32)['ok']
    assert not value.stop_backtest('b'*32)['ok']


def test_watch_and_capacity_validate_values(tmp_path):
    value, ref, jobs = bridge(tmp_path)
    value.start_backtest(ref['experiment_id'], ref['revision'])
    assert value.set_backtest_watch('a'*32, True)['ok']
    assert jobs.watch == [('a'*32, True)]
    assert value.set_backtest_capacity(4)['ok']
    assert not value.set_backtest_capacity(5)['ok']
