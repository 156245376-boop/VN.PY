from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from qf.config import load_config
from qf.runtime import execute


class Finished(Exception):
    pass


class Api:
    instances = []
    scenario = "normal"

    def __init__(self, **kwargs):
        assert kwargs["debug"] is False
        assert kwargs["disable_print"] is True
        assert kwargs["web_gui"] is False
        self.kwargs = kwargs
        self._data = {"notify": {}}
        self.steps = 0
        self.closed = False
        self.quotes = {}
        self.orders = {}
        self.trades = {}
        self.positions = {}
        self.account = NS(balance=100000., commission=0.)
        self.klines = pd.DataFrame({"datetime": [0] * 16, "close": [float("nan")] * 16})
        self.instances.append(self)

    def get_quote(self, symbol):
        quote = NS(underlying_symbol="SHFE.rb2610", datetime="2026-10-16 09:00:00",
                   last_price=3300., expired=False, expire_datetime=2_000_000_000.)
        self.quotes[symbol] = quote
        return quote

    def get_kline_serial(self, *args, **kwargs):
        return self.klines

    def get_account(self):
        return self.account

    def get_position(self):
        return self.positions

    def get_order(self):
        return self.orders

    def get_trade(self):
        return self.trades

    def wait_update(self, deadline=None):
        self.steps += 1
        if self.scenario == "denied":
            raise RuntimeError("secret_token=SHOULD_NOT_ESCAPE")
        if self.steps == 1:
            base = 1740963600000000000
            if self.scenario == "night_start":
                base = 1740747600000000000
            self.klines["datetime"] = [base + i * 60_000_000_000
                                       for i in range(1, 17)]
            self.klines["close"] = [10.] * 14 + [12., 999.]
        elif self.steps == 2:
            self.klines["datetime"] += 60_000_000_000
        else:
            raise Finished()
        if self.scenario == "disconnect":
            self._data["notify"]["n"] = {"code": 2019112911, "content": "private"}
        return True

    def insert_order(self, **kwargs):
        oid = f"owned-{len(self.orders)}"
        result = NS(order_id=oid, status="ALIVE", is_error=False,
                    volume_left=kwargs["volume"])
        self.orders[oid] = result
        return result

    def close(self):
        self.closed = True


class Sim:
    def __init__(self, init_balance):
        assert init_balance == 100000
        self.fee = 2.
        self.tqsdk_stat = {"end_balance": 100020., "commission": 12.}

    def get_commission(self, symbol):
        return self.fee

    def get_margin(self, symbol):
        return 3500.

    def set_commission(self, symbol, fee):
        self.fee = fee


class Target:
    def __init__(self, api, symbol):
        self.cancelled = False
        self.targets = []
        api.target = self

    def set_target_volume(self, target):
        self.targets.append(target)

    def cancel(self):
        self.cancelled = True

    def is_finished(self):
        return self.cancelled


@pytest.fixture
def sdk():
    Api.instances = []
    Api.scenario = "normal"
    return NS(TqApi=Api, TqSim=Sim, TqKq=lambda: NS(kind="kq"),
              TqBacktest=lambda **kwargs: NS(_start_dt=1740736800000000000,
                                            _end_dt=1741341600000000000, **kwargs),
              TqAuth=lambda user, password: object(), TargetPosTask=Target,
              BacktestFinished=Finished)


def config():
    return load_config(Path("experiments/rb-demo.toml"))


def test_data_check_explicit_local_account_and_no_target(tmp_path, sdk):
    result = execute("data-check", config(), tmp_path, ("u", "p"), sdk=sdk)
    assert result["status"] == "data_ready"
    assert result["symbol"] == "SHFE.rb2610"
    assert Api.instances[0].closed
    assert isinstance(Api.instances[0].kwargs["account"], Sim)
    assert not hasattr(Api.instances[0], "target")


def test_backtest_runs_baseline_and_double_fee_with_same_closed_signals(tmp_path, sdk):
    result = execute("backtest", config(), tmp_path, ("u", "p"), sdk=sdk)
    assert result["status"] == "backtest_finished"
    assert len(Api.instances) == 2
    assert [api.kwargs["account"].fee for api in Api.instances] == [2., 4.]
    assert all(api.closed for api in Api.instances)
    assert Api.instances[0].target.targets == [1, 1]
    assert Api.instances[1].target.targets == [1, 1]
    assert result["final_equity"] == 100020.
    assert result["commission"] == 12.


def test_failure_is_sanitized_and_session_is_closed(tmp_path, sdk):
    Api.scenario = "denied"
    result = execute("data-check", config(), tmp_path, ("u", "p"), sdk=sdk)
    assert result["status"] == "failed"
    assert "SHOULD_NOT_ESCAPE" not in str(result)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"SHOULD_NOT_ESCAPE" not in path.read_bytes()
    assert Api.instances[0].closed


def test_paper_disconnect_cancels_task_and_never_resumes(tmp_path, sdk):
    Api.scenario = "disconnect"
    result = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk, activate=True)
    assert result["status"] == "frozen"
    assert not hasattr(Api.instances[0], "target") or Api.instances[0].target.cancelled
    assert Api.instances[0].closed


def test_read_only_blocks_orders_at_actual_api_boundary(tmp_path, sdk):
    from qf.journal import Journal
    from qf.runtime import tracked_api
    from qf.safety import Frozen
    journal = Journal.create(tmp_path, "data-check", {})
    api = tracked_api(sdk, journal, account=Sim(100000), auth=object())
    with pytest.raises(Frozen):
        api.insert_order("SHFE.rb2610", "BUY", "OPEN", 1)
    assert api.orders == {}
    assert journal.owned() == set()
    journal.close()


def test_api_records_ownership_and_blocks_concurrent_second_order(tmp_path, sdk):
    from qf.journal import Journal
    from qf.runtime import tracked_api
    from qf.safety import Frozen, Guard
    journal = Journal.create(tmp_path, "paper", {})
    api = tracked_api(sdk, journal, account=NS(kind="kq"), auth=object())
    guard = Guard(journal, "SHFE.rb2610")
    guard.start({}, {}, activate=True)
    api.execution_guard = guard
    placed = api.insert_order("SHFE.rb2610", "BUY", "OPEN", 1)
    assert journal.owned() == {placed.order_id}
    with pytest.raises(Frozen):
        api.insert_order("SHFE.rb2610", "BUY", "OPEN", 1)
    assert len(api.orders) == 1
    journal.close()


def test_paper_observes_without_target_and_clean_resume_stays_deduplicated(tmp_path, sdk):
    import sqlite3
    result = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk,
                     stop_requested=lambda: Api.instances[-1].steps >= 2)
    assert result["status"] == "stopped"
    assert not hasattr(Api.instances[0], "target")
    db = sqlite3.connect(tmp_path / result["run_id"] / "journal.sqlite3")
    assert db.execute("select count(*) from signals").fetchone()[0] == 1
    db.close()
    resumed = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk,
                      resume=result["run_id"], stop_requested=lambda: Api.instances[-1].steps >= 2)
    assert resumed["status"] == "stopped"
    db = sqlite3.connect(tmp_path / result["run_id"] / "journal.sqlite3")
    assert db.execute("select count(*) from signals").fetchone()[0] == 1
    db.close()


def test_rejected_owned_order_freezes_before_new_target(tmp_path, sdk):
    class RejectApi(Api):
        def wait_update(self, deadline=None):
            updated = super().wait_update(deadline)
            if self.steps == 2:
                self.orders["external"] = NS(order_id="external", status="ALIVE", is_error=True,
                                             volume_left=1)
            return updated
    sdk.TqApi = RejectApi
    result = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk, activate=True)
    assert result["status"] == "frozen"
    assert Api.instances[0].target.cancelled


def test_backtest_includes_previous_friday_night_for_monday_trading_day(tmp_path, sdk):
    Api.scenario = "night_start"
    result = execute("backtest", config(), tmp_path, ("u", "p"), sdk=sdk)
    assert result["status"] == "backtest_finished"
    assert Api.instances[0].target.targets == [1, 1]


def test_resume_refuses_changed_code_before_creating_sdk_session(tmp_path, sdk, monkeypatch):
    import qf.runtime as runtime
    result = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk,
                     stop_requested=lambda: True)
    monkeypatch.setattr(runtime, "provenance", lambda: {"source_sha256": "different"})
    count = len(Api.instances)
    resumed = execute("paper", config(), tmp_path, ("u", "p"), sdk=sdk,
                      resume=result["run_id"], activate=True, stop_requested=lambda: True)
    assert resumed["status"] == "frozen"
    assert len(Api.instances) == count


def test_resume_does_not_time_out_a_target_never_submitted_in_this_process(
        tmp_path, sdk, monkeypatch):
    import itertools
    from dataclasses import replace

    import qf.runtime as runtime
    cfg = replace(config(), execution_timeout_seconds=1)
    result = execute("paper", cfg, tmp_path, ("u", "p"), sdk=sdk,
                     stop_requested=lambda: Api.instances[-1].steps >= 2)
    clock = itertools.count()
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(clock))
    resumed = execute("paper", cfg, tmp_path, ("u", "p"), sdk=sdk,
                      activate=True, resume=result["run_id"],
                      stop_requested=lambda: Api.instances[-1].steps >= 2)
    assert resumed["status"] == "stopped"
    assert Api.instances[-1].target.targets == []
