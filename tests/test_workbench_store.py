import importlib
import json

import pytest


def test_old_cache_contains_no_live_quotes_or_credentials(tmp_path):
    store_module = importlib.import_module("qf.workbench_store")
    store = store_module.WorkbenchStore(tmp_path)
    item = {"continuous": "KQ.m@SHFE.rb", "name": "螺纹钢", "exchange": "SHFE",
            "product": "rb", "last_price": 3300, "password": "private-password"}
    store.save([item], ["KQ.m@SHFE.rb"])
    restored = store_module.WorkbenchStore(tmp_path).load()
    assert restored["catalog"] == [{k: item[k] for k in
                                    ("continuous", "name", "exchange", "product")}]
    assert restored["favorites"] == ["KQ.m@SHFE.rb"]
    assert restored["cache_state"] == "cached"
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "private-" not in text and "last_price" not in text
    json.loads(text)


def test_corrupt_settings_is_reported_without_overwriting_original(tmp_path):
    store_module = importlib.import_module("qf.workbench_store")
    path = tmp_path / "settings.json"
    path.write_bytes(b"{broken")
    store = store_module.WorkbenchStore(tmp_path)
    result = store.load()
    assert result["cache_state"] == "corrupt" and result["issue"]
    with pytest.raises(ValueError):
        store.save([], [])
    assert path.read_bytes() == b"{broken"


def test_interrupted_atomic_save_retains_previous_file(tmp_path, monkeypatch):
    store_module = importlib.import_module("qf.workbench_store")
    store = store_module.WorkbenchStore(tmp_path)
    store.save([], [])
    before = (tmp_path / "settings.json").read_bytes()

    def fail_replace(*args):
        raise OSError("disk write failed")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.save([], ["KQ.m@SHFE.rb"])
    assert (tmp_path / "settings.json").read_bytes() == before
