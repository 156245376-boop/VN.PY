from test_continuous_config import continuous_data
from test_continuous_results import finished
from test_local_dataset_builder import write_validation

from qf.experiment_store import ExperimentStore
from qf.research_config import validate_research_config
from qf.research_jobs_bridge import ResearchJobsBridge


class FakeJobs:
    def __init__(self):
        self.capacity = 2
        self.submitted = []
        self.batch_submitted = []
        self.items = {}
        self.watch = []

    def submit(self, config, **kwargs):
        job_id = 'a'*32
        self.items[job_id] = {'job_id': job_id, 'status': 'waiting', 'running': False}
        self.submitted.append((config, kwargs))
        return {'job_ids': [job_id], 'selected_job_id': job_id}

    def list(self):
        return list(self.items.values())

    def submit_many(
        self,
        configs,
        *,
        credentials,
        experiment_refs,
        include_fee_stress,
        request_id=None,
        engine_kinds=None,
        compute_backends=None,
        dataset_ids=None,
    ):
        self.batch_submitted.append((
            configs,
            experiment_refs,
            include_fee_stress,
            request_id,
            engine_kinds,
            compute_backends,
            dataset_ids,
        ))
        ids = []
        groups = []
        for index, _config in enumerate(configs):
            job_id = f'{index+1:032x}'
            self.items[job_id] = {'job_id': job_id, 'status': 'waiting',
                                  'running': False}
            ids.append(job_id)
            groups.append([job_id])
        return {'job_ids': ids, 'groups': groups, 'selected_job_id': ids[0]}

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

    class Window:
        def __init__(self, job_id, state_provider, ledger_provider, chart_provider):
            self.job_id = job_id
            self.closed = False
        @staticmethod
        def open():
            return 'http://127.0.0.1:23456/'
        def close(self):
            self.closed = True

    monkeypatch.setattr('qf.research_jobs_bridge.ResearchWindowView', Window)
    response = value.open_backtest_window('a'*32)
    assert response['ok']
    assert opened == ['http://127.0.0.1:23456/']
    assert '独立浏览器窗口' in response['reason']
    assert '完整研究观察窗' in response['reason']


def test_bridge_uses_explicit_ssd_results_root(tmp_path):
    store = ExperimentStore(tmp_path/'experiments')
    target = tmp_path/'ssd-results'
    value = ResearchJobsBridge(tmp_path, store, results_root=target,
                               jobs=FakeJobs(), login=lambda: ('u', 'p'))
    assert value._jobs_args[0] == target


def test_batch_plan_submits_every_slot_in_order(tmp_path):
    value, ref, jobs = bridge(tmp_path)
    second = value.experiments.save(validate_research_config(continuous_data()))
    response = value.start_backtest_batch({
        'capacity': 2,
        'slots': [
            {'experiment_id': ref['experiment_id'], 'revision': ref['revision'],
             'include_fee_stress': False},
            {'experiment_id': second['experiment_id'], 'revision': second['revision'],
             'include_fee_stress': True},
        ],
    }, request_id='batch-1')
    assert response['ok']
    assert response['job_ids'] == ['0'*31+'1', '0'*31+'2']
    assert len(jobs.batch_submitted) == 1
    (configs, refs, stress, request_id, engines, backends,
     datasets) = jobs.batch_submitted[0]
    assert [config.schema_version for config in configs] == [3, 3]
    assert [item['experiment_id'] for item in refs] == [
        ref['experiment_id'], second['experiment_id']]
    assert stress == [False, True] and request_id == 'batch-1'
    assert engines == ['tqsdk_validation', 'tqsdk_validation']
    assert backends == ['cpu', 'cpu']
    assert datasets == [None, None]


def test_local_batch_reuses_verified_result_without_credentials(tmp_path):
    results = tmp_path/'results'
    cfg, _validation_id = write_validation(results)
    store = ExperimentStore(tmp_path/'experiments')
    ref = store.save(cfg)
    jobs = FakeJobs()
    value = ResearchJobsBridge(
        tmp_path,
        store,
        jobs=jobs,
        login=lambda: None,
    )
    response = value.start_backtest_batch({
        'capacity': 1,
        'slots': [{
            'experiment_id': ref['experiment_id'],
            'revision': ref['revision'],
            'include_fee_stress': False,
            'engine_kind': 'local_research',
            'compute_backend': 'cpu',
        }],
    })
    assert response['ok'], response
    _configs, _refs, _stress, _request, engines, backends, datasets = (
        jobs.batch_submitted[0]
    )
    assert engines == ['local_research']
    assert backends == ['cpu']
    assert datasets[0]


def test_batch_plan_validation_blocks_entire_batch(tmp_path):
    value, ref, jobs = bridge(tmp_path)
    response = value.start_backtest_batch({
        'capacity': 2,
        'slots': [
            {'experiment_id': ref['experiment_id'], 'revision': ref['revision'],
             'include_fee_stress': False},
            {'experiment_id': 'f'*32, 'revision': 1,
             'include_fee_stress': False},
        ],
    })
    assert not response['ok']
    assert jobs.batch_submitted == []
    assert 'slot_2' in response['field_errors']


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


def test_each_task_keeps_its_own_complete_research_window(tmp_path, monkeypatch):
    value, ref, jobs = bridge(tmp_path)
    jobs.items['a'*32] = dict(job_id='a'*32, status='active', running=True)
    jobs.items['b'*32] = dict(job_id='b'*32, status='active', running=True)
    created = []

    class FakeWindow:
        def __init__(self, job_id, state_provider, ledger_provider, chart_provider):
            self.job_id = job_id
            self.closed = False
            created.append(self)
        def open(self):
            return f'http://127.0.0.1:{42000+len(created)}/'
        def close(self):
            self.closed = True

    monkeypatch.setattr('qf.research_jobs_bridge.ResearchWindowView', FakeWindow)
    first = value.open_research_window('a'*32)
    second = value.open_research_window('b'*32)
    assert first['ok'] and second['ok'] and first['url'] != second['url']
    assert {view.job_id for view in created} == {'a'*32, 'b'*32}
    value.close()
    assert all(view.closed for view in created)
