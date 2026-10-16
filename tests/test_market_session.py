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
    mapping = "SHFE.rb2701"

    def __init__(self, account, *, auth, debug, disable_print, web_gui):
        assert account == "local-sim" and debug is False and disable_print is True
        self.thread_id = threading.get_ident()
        self.closed = False
        self.quotes = {}
        self.klines = []
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
        return pd.DataFrame([{"instrument_id": s, "instrument_name":
                              "螺纹钢" if "rb" in s else "豆粕"} for s in symbols])

    def get_quote(self, symbol):
        assert threading.get_ident() == self.thread_id
        self.quotes.setdefault(symbol, {})
        return self.quotes[symbol]

    def get_kline_serial(self, symbol, duration, data_length):
        assert duration == 60 and data_length == 200
        self.klines.append(symbol)
        return pd.DataFrame()

    def wait_update(self, **kwargs):
        for symbol, q in self.quotes.items():
            q.update(last_price=3300, pre_settlement=3000, volume=10, open_interest=20,
                     datetime="2026-10-16 14:59:59.000000",
                     underlying_symbol=type(self).mapping if "rb" in symbol else "DCE.m2701")
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


def test_stop_during_connect_closes_returned_api_and_masks_error(session):
    FakeApi.block = threading.Event()
    session.start("u", "p")
    until(lambda: bool(FakeApi.instances))
    session.stop()
    FakeApi.block.set()
    until(lambda: not session.running)
    assert FakeApi.instances[0].closed
    assert session.snapshot()["status"] == "stopped"


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
