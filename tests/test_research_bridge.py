import json

from research_helpers import pivot_config_data as config_data
from test_credentials import MemoryStore
from test_workbench import Session

from qf.research_session import ResearchSession
from qf.workbench import WorkbenchBridge


def test_bridge_rejects_live_traversal_foreign_contract_and_secret_fields(tmp_path):
    credentials = MemoryStore()
    credentials.save('u', 'private-password')
    calls = []
    def execute(mode, config, root, user_password, **kwargs):
        calls.append((mode, config))
        return {'status': 'stopped'}
    research = ResearchSession(tmp_path/'results', execute_fn=execute,
        discover_fn=lambda **kw: [{'symbol': 'SHFE.rb2505', 'name': '螺纹钢2505'}])
    bridge = WorkbenchBridge(tmp_path, Session(), credential_store=credentials,
                              research_session=research)
    bridge.get_state()
    assert not bridge.save_experiment(config_data() | {'password': 'private-password'})['ok']
    saved = bridge.save_experiment(config_data())
    assert saved['ok']
    ref = saved['experiment']
    assert not bridge.start_research('../secret', 1, 'backtest')['ok']
    assert not bridge.start_research(ref['experiment_id'], 1, 'live')['ok']
    assert not bridge.start_research(ref['experiment_id'], 1, 'backtest')['ok']
    assert bridge.get_research_contracts('KQ.m@SHFE.rb', '2025-03-03', '2025-03-07')['ok']
    research.thread.join(3)
    assert bridge.start_research(ref['experiment_id'], 1, 'backtest')['ok']
    research.thread.join(3)
    assert len(calls) == 1
    assert 'private-password' not in json.dumps(bridge.get_research_state())
