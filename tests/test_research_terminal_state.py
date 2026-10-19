import json
from urllib.request import urlopen

import pandas as pd
from research_helpers import pivot_config_data
from test_pivot_bridge import bridge_for

from qf.research_live_view import LiveResearchView


def test_expiry_conflict_is_blocked_before_job_or_sdk_start(tmp_path):
    calls = []
    def execute(*a, **kw):
        calls.append(1)
        return dict(status='stopped')
    bridge, session = bridge_for(tmp_path, execute)
    session.discover_fn = lambda **kw: [dict(symbol='SHFE.rb2505', name='螺纹钢2025年5月',
        expire_datetime=pd.Timestamp('2025-05-15 15:00', tz='Asia/Shanghai').timestamp())]
    raw = pivot_config_data() | {'end': '2026-10-07'}
    ref = bridge.save_experiment(raw)['experiment']
    assert bridge.get_research_contracts(raw['continuous'], raw['start'], raw['end'])['ok']
    session.thread.join(3)
    reply = bridge.start_research(ref['experiment_id'], ref['revision'], 'backtest')
    assert not reply['ok'] and reply['code'] == 'contract_range_exceeds_expiry'
    assert 'end' in reply['field_errors']
    assert all(value in reply['reason'] for value in ('SHFE.rb2505', '2026-10-07', '2025-05-15'))
    assert not calls and not (tmp_path/'results').exists()


def test_empty_terminal_job_cannot_open_an_endlessly_waiting_chart(tmp_path):
    bridge, session = bridge_for(tmp_path)
    session._state.update(job_id='fixture', status='frozen',
        reason='contract_range_exceeds_expiry', progress={'completed_bars': 0})
    result = bridge.open_research_live_chart()
    try:
        assert not result['ok'] and '结束' in result['reason']
        assert bridge._live_view.thread is None
    finally:
        bridge._live_view.close()


def test_already_open_empty_chart_receives_terminal_instead_of_waiting():
    state = dict(status='connecting', running=True, run_id=None, reason=None)
    view = LiveResearchView(lambda: None, state_provider=lambda: dict(state))
    try:
        url = view.open()
        assert json.loads(urlopen(url+'snapshot?after_revision=0').read())['waiting']
        state.update(status='frozen', running=False, reason='contract_range_exceeds_expiry',
                     password='private-test-value')
        packet = json.loads(urlopen(url+'snapshot?after_revision=0').read())
        assert packet['terminal'] and not packet['waiting']
        assert packet['reason'] == state['reason'] and 'snapshot' not in packet
        assert 'private-test-value' not in json.dumps(packet)
    finally:
        view.close()
