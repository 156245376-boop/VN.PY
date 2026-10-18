import copy
import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from test_credentials import MemoryStore

CATALOG = [{"continuous": "KQ.m@SHFE.rb", "name": "螺纹钢", "exchange": "SHFE", "product": "rb"},
           {"continuous": "KQ.m@DCE.m", "name": "豆粕", "exchange": "DCE", "product": "m"}]


class Session:
    def __init__(self):
        self.running = False
        self.state = {"status": "ready", "catalog": CATALOG, "rows": [],
                      "selected": "KQ.m@SHFE.rb", "chart_url": "http://127.0.0.1:12345",
                      "reason": "", "heartbeat_seconds": 15, "token": "private-token"}

    def start(self, user, password):
        self.running = True

    def snapshot(self):
        return copy.deepcopy(self.state)

    def set_view(self, symbols, selected, chart_mode="actual"):
        self.state["selected"] = selected
        self.state["chart_mode"] = chart_mode
        self.state["chart_url"] = None

    def stop(self):
        pass


@pytest.fixture
def bridge(tmp_path):
    module = importlib.import_module("qf.workbench")
    return module.WorkbenchBridge(tmp_path, Session(), credential_store=MemoryStore())


def test_bridge_serializes_only_public_fields(bridge):
    bridge._session.state["reason"] = "private-error"
    result = bridge.get_state()
    assert "private-" not in str(result)
    assert result["catalog"] == [{**row, "price_unit": "元/吨"}
                                 for row in [CATALOG[1], CATALOG[0]]]
    assert bridge.login("private-user", "private-password")["ok"]
    assert "private-" not in str(bridge.get_state())


def test_stale_selection_cannot_replace_current_chart(bridge):
    bridge.get_state()
    assert bridge.set_view(["KQ.m@DCE.m"], "KQ.m@DCE.m")["ok"]
    bridge._session.state.update(selected="KQ.m@SHFE.rb", chart_url="http://127.0.0.1:12345")
    state = bridge.get_state()
    assert state["selected"] == "KQ.m@DCE.m" and state["chart_url"] is None


def test_chart_mode_and_loading_are_validated_without_exposing_raw_objects(bridge):
    bridge.get_state()
    assert not bridge.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb", "unknown")["ok"]
    assert bridge.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb", "continuous")["ok"]
    bridge._session.state.update(chart_mode="actual", chart_url="http://127.0.0.1:12345",
                                 chart_symbol={"token": "private-token"},
                                 loading={"phase": "private-response", "done": "private-token",
                                          "total": 88, "elapsed_seconds": 4})
    result = bridge.get_state()
    assert result["chart_url"] is None
    assert result["chart_symbol"] is None
    assert result["loading"] == {"phase": "idle", "done": None, "total": 88,
                                 "elapsed_seconds": 4}
    assert "private-" not in str(result)


def test_resource_keys_do_not_execute_arbitrary_commands(bridge):
    assert not bridge.open_resource("powershell.exe")["ok"]
    assert not bridge.open_resource("https://example.com/private-token")["ok"]
    assert not bridge.open_resource("../../secret")["ok"]


def test_history_summary_is_whitelisted_and_bound_to_current_selection(bridge):
    bridge._session.state.update(chart_revision=12, history={
        "valid_count": 2, "first": "2016-01-05 00:00:00", "last": "2026-10-16 00:00:00",
        "years": {"2016": 1, "2026": 1, "private-token": 4},
        "issues": ["long_gap", "private-response"], "token": "private-token"})
    result = bridge.get_state()
    assert result["history"] == {
        "valid_count": 2, "first": "2016-01-05 00:00:00", "last": "2026-10-16 00:00:00",
        "years": {"2016": 1, "2026": 1}, "issues": ["long_gap"]}
    assert result["chart_revision"] == 12
    assert "private-" not in str(result)
    bridge.set_view(["KQ.m@DCE.m"], "KQ.m@DCE.m")
    bridge._session.state["selected"] = "KQ.m@SHFE.rb"
    result = bridge.get_state()
    assert result["history"] is None
    assert result["chart_revision"] == 0


def test_malformed_history_fields_do_not_escape_to_page(bridge):
    bridge._session.state.update(chart_revision="private-token", history={
        "valid_count": "private-token", "first": {"token": "private-token"},
        "last": "private-token", "years": ["private-token"], "issues": "private-token"})
    result = bridge.get_state()
    assert result["chart_revision"] == 0
    assert result["history"] == {
        "valid_count": 0, "first": None, "last": None, "years": {}, "issues": []}
    assert "private-" not in str(result)


def test_favorites_are_validated_and_survive_restart(bridge):
    module = importlib.import_module("qf.workbench")
    bridge.get_state()
    assert bridge.set_favorites(["KQ.m@SHFE.rb"])["ok"]
    assert not bridge.set_favorites(["unknown"])["ok"]
    restored = module.WorkbenchBridge(bridge._root, Session()).get_state()
    assert restored["favorites"] == ["KQ.m@SHFE.rb"]
    assert (bridge._root / "data/workbench/settings.json").exists()


def test_closing_window_waits_until_disconnect_finishes(bridge):
    bridge._session.running = True
    assert bridge._request_close() is False
    bridge._session.running = False
    assert bridge._request_close() is True


def test_missing_credentials_and_bad_chart_never_escape(bridge):
    assert not bridge.login("", "")["ok"]
    bridge._session.state["chart_url"] = "https://example.com/?token=private-token"
    assert bridge.get_state()["chart_url"] is None
    assert not bridge.set_view(["KQ.m@SHFE.rb"], "not-a-contract")["ok"]


def test_remembered_credentials_connect_without_returning_password_to_page(bridge):
    module = importlib.import_module("qf.workbench")
    received = []
    bridge._session.start = lambda user, password: received.append((user, password))
    assert bridge.login("offline-user", "private-password", True)["ok"]
    bridge.get_state()  # 连接成功才保存。
    restored = module.WorkbenchBridge(bridge._root, Session(),
                                      credential_store=bridge._login._store)
    restored._session.start = lambda user, password: received.append((user, password))
    assert restored.get_login_state()["user"] == "offline-user"
    assert restored.login("offline-user", "", True)["ok"]
    assert received == [("offline-user", "private-password")] * 2
    assert "private-password" not in str(restored.get_state()) + str(restored.get_login_state())
    assert restored.forget_login()["ok"]
    assert not restored.get_login_state()["saved"]
    assert not restored.login("offline-user", "", True)["ok"]


def test_workspace_restore_never_connects_or_returns_credentials(bridge):
    from qf.chart_workspace import default_workspace
    config = default_workspace()
    config['layout'] = 'quad'
    assert bridge.save_workspace(config)['ok']
    assert bridge.get_workspace()['workspace'] == config
    assert bridge._session.running is False
    assert 'private-' not in str(bridge.get_workspace())


def test_workspace_requests_and_snapshot_are_whitelisted(bridge):
    bridge.get_state()
    requests = [{'id': 'pane-1', 'continuous': 'KQ.m@SHFE.rb', 'mode': 'actual',
                 'period': '1m', 'revision': 10}]
    bridge._session.set_workspace = lambda symbols, panes: None
    assert bridge.set_workspace([], requests)['ok']
    assert not bridge.set_workspace([], [requests[0] | {'id': 'other'}])['ok']
    bridge._session.state.update(generation=2, panes=[requests[0] | {
        'status': 'ready', 'symbol': 'SHFE.rb2701', 'duration': 60000000000,
        'history': None, 'token': 'private-token'}], rows=[{'continuous': 'KQ.m@SHFE.rb',
                                                        'underlying': 'SHFE.rb2701'}])
    output = bridge.get_state()
    assert output['generation'] == 2 and output['panes'][0]['revision'] == 10
    assert 'private-' not in str(output)
    bridge._session.state['panes'][0]['revision'] = 9
    assert bridge.get_state()['panes'] == []


def test_real_workbench_search_selection_favorites_chart_and_disconnect():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("workbench_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORKBENCH_SMOKE=" in result.stdout


def test_workspace_lifecycle_in_real_webview(tmp_path):
    for phase in ('write', 'read'):
        result = subprocess.run(
            [sys.executable, '-I', '-B', '-X', 'utf8',
             str(Path(__file__).with_name('workspace_lifecycle_smoke.py')), str(tmp_path), phase],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'WORKSPACE_LIFECYCLE_OK' in result.stdout
