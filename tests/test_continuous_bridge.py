from research_helpers import pivot_config_data
from test_continuous_config import continuous_data
from test_pivot_bridge import bridge_for


def test_years_need_no_fixed_contract_query(tmp_path):
    calls = []
    bridge, session = bridge_for(tmp_path,
        lambda mode, config, *a, **kw: calls.append(config) or dict(status='stopped'))
    discovers = []
    session.discover_fn = lambda **kw: discovers.append(kw) or []
    saved = bridge.save_experiment(continuous_data())
    assert saved['ok']
    ref = saved['experiment']
    reply = bridge.start_research(ref['experiment_id'], ref['revision'], 'backtest')
    assert reply['ok'], reply
    session.thread.join(3)
    assert len(calls) == 1 and not discovers


def test_continuous_paper_rejected_before_credentials(tmp_path, monkeypatch):
    bridge, session = bridge_for(tmp_path)
    saved = bridge.save_experiment(continuous_data())['experiment']
    monkeypatch.setattr(bridge, '_research_login', lambda: (_ for _ in ()).throw(AssertionError()))
    reply = bridge.start_research(saved['experiment_id'], saved['revision'], 'paper')
    assert not reply['ok'] and reply['code'] == 'continuous_backtest_only'
    assert session.thread is None


def test_fixed_to_continuous_requires_explicit_copy_and_preserves_original(tmp_path):
    bridge, _ = bridge_for(tmp_path)
    old = bridge.save_experiment(pivot_config_data())['experiment']
    path = bridge._experiments._folder(old['experiment_id'])/'1.toml'
    before = path.read_bytes()
    assert not bridge.save_experiment(continuous_data(), old['experiment_id'])['ok']
    new = bridge.copy_continuous_experiment(old['experiment_id'], 1, '跨年度研究')
    assert new['ok']
    assert new['experiment']['experiment_id'] != old['experiment_id']
    assert new['config']['schema_version'] == 3 and new['config']['symbol'] is None
    assert path.read_bytes() == before
