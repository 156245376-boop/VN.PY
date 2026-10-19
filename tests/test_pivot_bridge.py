import threading

from research_helpers import config_data, pivot_config_data
from test_credentials import MemoryStore
from test_workbench import Session

from qf.research_session import ResearchSession
from qf.workbench import WorkbenchBridge


def bridge_for(root, execute=None):
    store = MemoryStore()
    store.save('fixture', 'private-password')
    session = ResearchSession(root/'results', execute_fn=execute,
        discover_fn=lambda **kw: [{'symbol': 'SHFE.rb2505', 'name': '螺纹钢2505'}])
    bridge = WorkbenchBridge(root, Session(), credential_store=store, research_session=session)
    bridge.get_state()
    return bridge, session


def test_missing_contract_points_to_field_without_creating_run(tmp_path):
    bridge, session = bridge_for(tmp_path)
    result = bridge.save_experiment(pivot_config_data() | {'symbol': ''})
    assert not result['ok'] and 'symbol' in result['field_errors']
    assert not session.running and not (tmp_path/'results').exists()


def test_contract_query_needs_no_risk_fields(tmp_path):
    bridge, session = bridge_for(tmp_path)
    reply = bridge.get_research_contracts('KQ.m@SHFE.rb', '2025-03-03', '2025-03-07')
    assert reply['ok'] and type(reply['request_id']) is int
    session.thread.join(3)
    assert session.snapshot()['request_id'] == reply['request_id']
    bad = bridge.get_research_contracts('KQ.m@SHFE.rb', '2025-03-03', 'bad-date')
    assert not bad['ok'] and 'end' in bad['field_errors']


def test_stale_contract_reply_and_double_click_cannot_start_twice(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def execute(*args, **kw):
        calls.append(args[1])
        entered.set()
        release.wait(3)
        return dict(status='stopped')
    bridge, session = bridge_for(tmp_path, execute)
    saved = bridge.save_experiment(pivot_config_data())['experiment']
    assert bridge.get_research_contracts('KQ.m@SHFE.rb','2025-03-03','2025-03-06')['ok']
    session.thread.join(3)
    bad = bridge.start_research(saved['experiment_id'], saved['revision'], 'backtest')
    assert not bad['ok'] and 'symbol' in bad['field_errors']
    bridge.get_research_contracts('KQ.m@SHFE.rb','2025-03-03','2025-03-07')
    session.thread.join(3)
    try:
        answer = bridge.start_research(saved['experiment_id'], saved['revision'], 'backtest')
        assert answer['ok'] and answer['job_id']
        assert entered.wait(2)
        duplicate = bridge.start_research(saved['experiment_id'], saved['revision'], 'backtest')
        assert not duplicate['ok']
        assert len(calls) == 1
    finally:
        release.set()
        session.thread.join(3)


def test_legacy_copy_is_explicit_and_original_is_unchanged(tmp_path):
    bridge, _ = bridge_for(tmp_path)
    saved = bridge.save_experiment(config_data())['experiment']
    reply = bridge.copy_experiment(saved['experiment_id'], saved['revision'], '新版', True)
    assert reply['ok'] and reply['config']['strategy_version'] == 2
    original = bridge._experiments.load(saved['experiment_id'], saved['revision'])
    assert original.strategy_version == 1
