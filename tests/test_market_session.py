import importlib
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest


def until(predicate):
    end = time.monotonic() + 4
    while not predicate() and time.monotonic() < end:
        time.sleep(0.01)
    assert predicate()


class FakeApi:
    instances = []
    block = None
    catalog_block = None
    mapping = "SHFE.rb2701"
    missing = set()
    fail_kline = False

    def __init__(self, account, *, auth, debug, disable_print, web_gui):
        assert account == "local-sim" and debug is False and disable_print is True
        self.thread_id = threading.get_ident()
        self.closed = False
        self.quotes = {}
        self.klines = []
        self.kline_requests = []
        self._data = {"notify": {}}
        self.address = web_gui
        type(self).instances.append(self)
        print("private-auth-response")
        if type(self).block:
            type(self).block.wait(3)

    def query_quotes(self, **kwargs):
        assert kwargs == {"ins_class": "CONT"}
        return ["KQ.m@SHFE.rb", "KQ.m@DCE.m"]

    def query_symbol_info(self, symbols):
        if type(self).catalog_block:
            type(self).catalog_block.wait(8)
        return pd.DataFrame([{"instrument_id": s, "instrument_name":
                              "螺纹钢" if "rb" in s else "豆粕"} for s in symbols])

    def get_quote(self, symbol):
        assert threading.get_ident() == self.thread_id
        self.quotes.setdefault(symbol, {})
        return self.quotes[symbol]

    def get_kline_serial(self, symbol, duration, data_length):
        assert (duration, data_length) in ((60, 200), (86400, 3000))
        if type(self).fail_kline:
            raise RuntimeError("private-kline-permission-response")
        self.klines.append(symbol)
        self.kline_requests.append((symbol, duration, data_length))
        return pd.DataFrame()

    def wait_update(self, **kwargs):
        for symbol, q in self.quotes.items():
            q.update(last_price=3300, pre_settlement=3000, volume=10, open_interest=20,
                     datetime="2026-10-16 14:59:59.000000",
                     underlying_symbol=type(self).mapping if "rb" in symbol else "DCE.m2701")
            if symbol in type(self).missing:
                q.update(last_price=float("nan"), datetime="", volume=0, open_interest=0)
        self._print(f"您可以访问 {self.address} 查看策略绘制出的 K 线图形。")
        time.sleep(0.01)

    def _print(self, *args, **kwargs):
        pass

    def insert_order(self, *args, **kwargs):
        pytest.fail("只读会话不得下单")

    def close(self):
        assert threading.get_ident() == self.thread_id
        self.closed = True


@pytest.fixture
def session():
    module = importlib.import_module("qf.market_session")
    FakeApi.instances, FakeApi.block, FakeApi.mapping = [], None, "SHFE.rb2701"
    FakeApi.catalog_block = None
    FakeApi.missing, FakeApi.fail_kline = set(), False
    sdk = SimpleNamespace(TqApi=FakeApi, TqSim=lambda: "local-sim",
                          TqAuth=lambda u, p: (u, p))
    item = module.MarketSession(sdk=sdk)
    yield item
    item.stop()
    if item.thread:
        item.thread.join(4)


def test_readonly_session_never_inserts_orders(session, capsys):
    session.start("private-user", "private-password")
    until(lambda: session.snapshot()["status"] == "ready")
    until(lambda: bool(session.snapshot()["chart_url"]))
    snapshot = session.snapshot()
    assert snapshot["rows"][0]["data_state"] == "ready"
    assert "private-" not in str(snapshot) + str(capsys.readouterr())
    with pytest.raises(RuntimeError, match="只读"):
        FakeApi.instances[-1].insert_order("SHFE.rb2701")
    session.stop()
    until(lambda: not session.running)
    assert all(api.closed for api in FakeApi.instances)
    assert session.snapshot()["chart_url"] is None


def test_latest_selection_wins_and_subscription_budget_is_bounded(session):
    session.start("u", "p")
    until(lambda: session.snapshot()["status"] == "ready")
    session.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb")
    session.set_view(["KQ.m@DCE.m"], "KQ.m@DCE.m")
    until(lambda: session.snapshot()["selected"] == "KQ.m@DCE.m"
          and bool(session.snapshot()["chart_url"]))
    assert FakeApi.instances[-1].klines[-1] == "DCE.m2701"
    with pytest.raises(ValueError):
        session.set_view([f"KQ.m@SHFE.p{'a' * i}" for i in range(101)], None)


def test_main_mapping_changes_update_display_without_trading(session):
    session.start("u", "p")
    until(lambda: session.snapshot()["chart_url"] is not None)
    FakeApi.mapping = "SHFE.rb2705"
    until(lambda: "SHFE.rb2705" in FakeApi.instances[-1].klines)
    until(lambda: any(r["underlying"] == "SHFE.rb2705" for r in session.snapshot()["rows"]))


def test_mapping_update_never_publishes_a_chart_for_the_previous_contract(session):
    published = []
    original = session._publish

    def capture(**values):
        if values.get("chart_url") and values.get("rows"):
            actual = next(r["underlying"] for r in values["rows"]
                          if r["continuous"] == "KQ.m@SHFE.rb")
            published.append((actual, FakeApi.instances[-1].klines[-1]))
        original(**values)

    session._publish = capture
    session.start("u", "p")
    until(lambda: bool(published))
    FakeApi.mapping = "SHFE.rb2705"
    until(lambda: ("SHFE.rb2705", "SHFE.rb2705") in published)
    assert all(display == chart for display, chart in published), published


def test_stop_during_connect_closes_returned_api_and_masks_error(session):
    FakeApi.block = threading.Event()
    session.start("u", "p")
    until(lambda: bool(FakeApi.instances))
    session.stop()
    FakeApi.block.set()
    until(lambda: not session.running)
    assert FakeApi.instances[0].closed
    assert session.snapshot()["status"] == "stopped"


def test_cached_view_without_selection_still_receives_default_chart(session):
    FakeApi.block = threading.Event()
    session.start("u", "p")
    until(lambda: bool(FakeApi.instances))
    session.set_view(["KQ.m@DCE.m", "KQ.m@SHFE.rb"], None)
    FakeApi.block.set()
    until(lambda: session.snapshot()["selected"] == "KQ.m@SHFE.rb"
          and bool(session.snapshot()["chart_url"]))


def test_continuous_history_selection_does_not_reuse_actual_contract_chart(session):
    session.start("u", "p")
    until(lambda: bool(session.snapshot()["chart_url"]))
    session.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb", "continuous")
    until(lambda: session.snapshot().get("chart_mode") == "continuous"
          and bool(session.snapshot()["chart_url"]))
    assert FakeApi.instances[-1].klines[-1] == "KQ.m@SHFE.rb"
    assert FakeApi.instances[-1].kline_requests[-1] == ("KQ.m@SHFE.rb", 86400, 3000)
    assert session.snapshot()["chart_symbol"] == "KQ.m@SHFE.rb"
    session.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb", "actual")
    until(lambda: session.snapshot().get("chart_mode") == "actual"
          and bool(session.snapshot()["chart_url"]))
    assert FakeApi.instances[-1].klines[-1] == "SHFE.rb2701"
    with pytest.raises(ValueError):
        session.set_view(["KQ.m@SHFE.rb"], "KQ.m@SHFE.rb", "unknown")


def test_loading_stage_tracks_connect_and_completion_without_guessing_eta(session):
    FakeApi.block = threading.Event()
    session.start("u", "p")
    until(lambda: bool(FakeApi.instances))
    loading = session.snapshot()["loading"]
    assert loading["phase"] == "connecting"
    assert loading["total"] is None and loading["elapsed_seconds"] >= 0
    FakeApi.block.set()
    until(lambda: bool(session.snapshot()["chart_url"]))
    assert session.snapshot()["loading"]["phase"] == "ready"


def test_connection_indicator_is_independent_of_missing_quotes(session):
    FakeApi.missing = {"KQ.m@SHFE.rb", "KQ.m@DCE.m"}
    session.start("u", "p")
    until(lambda: bool(session.snapshot()["rows"]))
    assert session.snapshot()["status"] == "waiting_data"
    assert session.snapshot()["connected"] is True
    assert all(r["data_state"] == "waiting" and r["volume"] is None
               for r in session.snapshot()["rows"])
    session.stop()
    until(lambda: not session.running)
    assert session.snapshot()["connected"] is False


def test_kline_read_failure_does_not_stop_other_quotes_or_leak_error(session):
    FakeApi.fail_kline = True
    session.start("u", "p")
    until(lambda: session.snapshot()["chart_status"] == "unavailable")
    state = session.snapshot()
    assert state["status"] == "ready" and state["connected"] is True
    assert state["rows"] and state["chart_url"] is None
    assert state["reason"] == "chart_data_unavailable" and "private-" not in str(state)


def test_heartbeat_does_not_replace_quote_timestamp(session):
    session.start("u", "p")
    until(lambda: session.snapshot()["status"] == "ready")
    first = session.snapshot()["rows"][0]["quote_time"]
    FakeApi.instances[-1]._data["notify"]["lost"] = {"code": 2019112911,
                                                    "content": "private-token"}
    until(lambda: session.snapshot()["status"] == "disconnected")
    assert session.snapshot()["rows"][0]["quote_time"] == first
    assert "private-" not in str(session.snapshot())


def test_other_connection_recovery_does_not_hide_lost_feed(session):
    session.start("u", "p")
    until(lambda: session.snapshot()["status"] == "ready")
    FakeApi.instances[-1]._data["notify"].update({
        "lost": {"code": 2019112911, "conn_id": "md"},
        "other": {"code": 2019112902, "conn_id": "metadata"},
    })
    until(lambda: session.snapshot()["status"] == "disconnected")
