import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from qf.config import load_config
from qf.journal import Journal, PaperLock
from qf.strategy import completed_signal


def bars(closes):
    return [{"datetime": (i + 1) * 60_000_000_000, "close": c}
            for i, c in enumerate(closes)]


def test_signal_ignores_forming_bar_and_requires_full_warmup():
    assert completed_signal(bars([10] * 14 + [12, -999]), 15) == (900_000_000_000, 1)
    assert completed_signal(bars([10] * 14 + [8, 999]), 15) == (900_000_000_000, 0)
    assert completed_signal(bars([10] * 15), 15) is None
    assert completed_signal(bars([10] * 14 + [float("nan"), 12]), 15) is None
    invalid = bars([10] * 16)
    invalid[-2]["datetime"] = invalid[-3]["datetime"]
    assert completed_signal(invalid, 15) is None


def test_config_rejects_unknown_secret_and_unsafe_values(tmp_path):
    config = load_config(Path("experiments/rb-demo.toml"))
    assert str(config.start) == "2025-03-03"
    for extra in ['password="secret"', 'lots=2', 'period=0']:
        path = tmp_path / "bad.toml"
        path.write_text(extra, encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(path)


def test_journal_commits_checkpoint_intent_and_deduplicates_fills(tmp_path):
    journal = Journal.create(tmp_path, "backtest", {"symbol": "SHFE.rb2505"})
    assert journal.signal(60, 1)
    assert not journal.signal(60, 1)
    fill = {"key": "day/exchange/id", "order_id": "o1", "symbol": "SHFE.rb2505",
            "direction": "BUY", "offset": "OPEN", "volume": 1, "price": 3300.0,
            "time_ns": 70}
    journal.fill(fill)
    journal.fill(fill)
    journal.equity(70, 100010.0, 2.0)
    journal.export()
    db = sqlite3.connect(journal.path / "journal.sqlite3")
    assert db.execute("select count(*) from fills").fetchone()[0] == 1
    assert db.execute("select count(*) from signals").fetchone()[0] == 1
    assert (journal.path / "fills.csv").exists()
    assert json.loads((journal.path / "metadata.json").read_text())["mode"] == "backtest"
    assert "100010" in (journal.path / "report.md").read_text(encoding="utf-8")
    journal.close()


def test_paper_lock_releases_after_owner_exit_and_never_steals_live_lock(tmp_path):
    with PaperLock(tmp_path):
        with pytest.raises(ValueError):
            with PaperLock(tmp_path):
                pass
    with PaperLock(tmp_path):
        pass


def test_resume_requires_same_configuration_and_keeps_checkpoint(tmp_path):
    journal = Journal.create(tmp_path, "paper", {"symbol": "SHFE.rb"})
    journal.signal(120, 1)
    path = journal.path
    journal.close()
    with pytest.raises(ValueError):
        Journal.resume(path, {"symbol": "SHFE.cu"})
    resumed = Journal.resume(path, {"symbol": "SHFE.rb"})
    assert not resumed.signal(120, 0)
    resumed.close()


def test_forced_process_exit_releases_account_lock(tmp_path):
    root = str(Path(__file__).resolve().parent.parent)
    program = ("import sys,time;sys.path.insert(0,sys.argv[1]);"
               "from pathlib import Path;from qf.journal import PaperLock;"
               "lock=PaperLock(Path(sys.argv[2]));lock.__enter__();"
               "print('locked',flush=True);time.sleep(30)")
    child = subprocess.Popen([sys.executable, "-I", "-c", program, root, str(tmp_path)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError):
            with PaperLock(tmp_path):
                pass
    finally:
        child.kill()
        child.communicate(timeout=5)
    with PaperLock(tmp_path):
        pass
