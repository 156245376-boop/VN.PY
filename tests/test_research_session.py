import json
import threading

import pytest
from research_helpers import config_data

from qf.research_config import validate_research_config
from qf.research_session import ResearchSession


def test_double_start_and_draft_edit_cannot_mutate_run(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def execute(mode, config, root, credentials, **kwargs):
        calls.append(config)
        entered.set()
        release.wait(5)
        return {'status': 'stopped', 'reason': 'requested_stop'}
    session = ResearchSession(tmp_path, execute_fn=execute)
    raw = config_data()
    original = validate_research_config(raw)
    session.start('backtest', original, ('user', 'private-password'), experiment_ref={})
    assert entered.wait(2)
    try:
        raw['fast_period'] = 10
        with pytest.raises(ValueError):
            session.start('backtest', original, ('u', 'p'), experiment_ref={})
        assert calls == [original]
        assert 'private-password' not in json.dumps(session.snapshot())
    finally:
        release.set()
        session.thread.join(3)


def test_saved_login_is_not_returned_and_paper_requires_activate(tmp_path):
    values = []
    def execute(mode, config, root, credentials, **kwargs):
        values.append(kwargs['activate'])
        kwargs['progress']('research_state', phase='holding',
                           risk={'last_quote_ns': 1740963600000000001}, token='private-token')
        return {'status': 'stopped', 'reason': 'requested_stop', 'token': 'private-token'}
    session = ResearchSession(tmp_path, execute_fn=execute)
    session.start('paper', validate_research_config(config_data()), ('u', 'p'), experiment_ref={})
    session.thread.join(3)
    snapshot = session.snapshot()
    assert values == [False]
    assert 'private-token' not in json.dumps(snapshot)
    assert snapshot['risk']['last_quote_ns'] == '1740963600000000001'


def test_close_with_pending_position_finishes_without_claiming_flat(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def execute(*args, **kwargs):
        kwargs['progress']('research_state', phase='holding', risk={'quantity': 2})
        entered.set()
        release.wait(5)
        return {'status': 'stopped'}
    session = ResearchSession(tmp_path, execute_fn=execute)
    session.start('paper', validate_research_config(config_data()), ('u', 'p'), experiment_ref={})
    assert entered.wait(2)
    try:
        assert not session.close()
        monkeypatch.setattr('qf.research_session.time.monotonic', lambda: 10**12)
        assert session.close()
        assert session.snapshot()['status'] == 'frozen'
        assert session.snapshot()['risk']['quantity'] == 2
    finally:
        release.set()
        session.thread.join(3)
