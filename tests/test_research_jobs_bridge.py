from test_continuous_config import continuous_data
from test_continuous_results import finished

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

    def remove(self, job_id):
        if job_id not in self.items:
            raise KeyError(job_id)
        self.items.pop(job_id)

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


def test_waiting_task_can_be_removed(tmp_path):
    value, ref, jobs = bridge(tmp_path)
    value.start_backtest(ref['experiment_id'], ref['revision'])
    assert value.remove_backtest('a'*32)['ok']
    assert value.list_backtest_jobs()['jobs'] == []
    assert not value.remove_backtest('a'*32)['ok']


def test_trade_ledger_is_read_from_the_selected_completed_run(tmp_path):
    results = tmp_path/'results'
    journal = finished(results)
    try:
        value, ref, jobs = bridge(tmp_path)
        value.start_backtest(ref['experiment_id'], ref['revision'])
        jobs.items['a'*32]['run_id'] = journal.path.name
        response = value.get_trade_ledger('a'*32)
        assert response['ok'] and response['ledger']['reconciled']
        assert response['ledger']['trades'][0]['net_pnl'] == '1992'
    finally:
        journal.close()


def test_independent_chart_window_uses_validated_local_url(tmp_path, monkeypatch):
    value, ref, jobs = bridge(tmp_path)
    value.start_backtest(ref['experiment_id'], ref['revision'])
    jobs.items['a'*32]['run_id'] = '20261020T000000-abcdef123456'
    opened = []
    monkeypatch.setattr('qf.research_jobs_bridge.webbrowser.open_new',
                        lambda url: opened.append(url) or True)

    class Replay:
        revision = 'fixture'
        @staticmethod
        def open(run_id):
            return 'http://127.0.0.1:23456/'+run_id

    value.replay = Replay()
    response = value.open_backtest_window('a'*32)
    assert response['ok']
    assert opened == ['http://127.0.0.1:23456/20261020T000000-abcdef123456']
    assert '独立浏览器窗口' in response['reason']


def test_bridge_uses_explicit_ssd_results_root(tmp_path):
    store = ExperimentStore(tmp_path/'experiments')
    target = tmp_path/'ssd-results'
    value = ResearchJobsBridge(tmp_path, store, results_root=target,
                               jobs=FakeJobs(), login=lambda: ('u', 'p'))
    assert value._jobs_args[0] == target


def test_each_task_keeps_its_own_live_chart_server(tmp_path, monkeypatch):
    value, ref, jobs = bridge(tmp_path)
    jobs.items['a'*32] = dict(job_id='a'*32, run_id='run-a', status='active',
                              running=True)
    jobs.items['b'*32] = dict(job_id='b'*32, run_id='run-b', status='active',
                              running=True)
    jobs.live_snapshot = lambda job_id: dict(run_id='run-'+job_id[0])
    created = []

    class FakeLive:
        def __init__(self, provider, *, state_provider):
            self.provider, self.state_provider = provider, state_provider
            self.generation = len(created)+1
            self.closed = False
            created.append(self)
        def open(self):
            return f'http://127.0.0.1:{41000+len(created)}/'
        def close(self):
            self.closed = True

    monkeypatch.setattr('qf.research_jobs_bridge.LiveResearchView', FakeLive)
    first = value.open_backtest_chart('a'*32)
    second = value.open_backtest_chart('b'*32)
    assert first['ok'] and second['ok'] and first['url'] != second['url']
    assert len(created) == 2
    value.close()
    assert all(view.closed for view in created)
