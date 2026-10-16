"""原生能力清单只做离线检查，示例源码永远不执行。"""

import base64
import csv
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import tqsdk


@pytest.fixture
def local_wheel(tmp_path, monkeypatch):
    sdk_root = tmp_path / "tqsdk"
    sdk_root.mkdir()
    (sdk_root / "__init__.py").write_text("", encoding="utf-8")
    contents = {
        "tqsdk/demo/tutorial/demo.py": "raise RuntimeError('example must never run')\n",
        "tqsdk/demo/__init__.py": "",
        "tqsdk/web/index.html": "<html>local chart</html>\n",
    }
    rows = []
    for name, source in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = source.encode("utf-8")
        path.write_bytes(raw)
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        rows.append((name, f"sha256={digest}", len(raw)))
    metadata_root = tmp_path / "tqsdk-3.10.2.dist-info"
    metadata_root.mkdir()
    (metadata_root / "METADATA").write_text("Name: tqsdk\nVersion: 3.10.2\n", encoding="utf-8")
    with (metadata_root / "RECORD").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)
    distribution = importlib.metadata.PathDistribution(metadata_root)
    original_distribution = importlib.metadata.distribution
    monkeypatch.setattr(tqsdk, "__file__", str(sdk_root / "__init__.py"))
    monkeypatch.setattr(
        importlib.metadata, "distribution",
        lambda name: distribution if name == "tqsdk" else original_distribution(name),
    )
    return sdk_root, metadata_root


def test_inventory_has_real_counts_without_creating_api(monkeypatch):
    from qf import native_catalog

    def forbidden(*args, **kwargs):
        pytest.fail("离线清单不得创建 TqApi 会话")

    monkeypatch.setattr(tqsdk.TqApi, "__init__", forbidden)
    inventory = native_catalog.inspect_installation()
    json.dumps(inventory, ensure_ascii=False)
    assert inventory["sdk_version"] == "3.10.2"
    assert inventory["ta_functions"] == 70
    assert inventory["tafunc_functions"] == 41
    assert inventory["web_assets"] == 45
    assert len(inventory["examples"]) == 86
    assert inventory["examples"] == sorted(inventory["examples"])
    assert all(name.endswith(".py") and not name.endswith("__init__.py")
               for name in inventory["examples"])
    assert inventory["ready"] is (not inventory["issues"])
    assert inventory["resource_integrity"]["checked_files"] == 135
    assert inventory["resource_integrity"]["method"] == "wheel RECORD hashes (demo + web)"


@pytest.mark.parametrize("relative_name", ["demo/tutorial/demo.py", "web/index.html"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_corrupt_wheel_resources_fail_inventory(local_wheel, relative_name, damage):
    from qf import native_catalog

    sdk_root, _ = local_wheel
    path = sdk_root / relative_name
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("corrupted", encoding="utf-8")
    inventory = native_catalog.inspect_installation()
    assert inventory["ready"] is False
    assert any(relative_name in issue for issue in inventory["issues"])


def test_missing_record_cannot_claim_integrity(local_wheel):
    from qf import native_catalog

    _, metadata_root = local_wheel
    (metadata_root / "RECORD").unlink()
    inventory = native_catalog.inspect_installation()
    assert inventory["ready"] is False
    assert any("RECORD" in issue for issue in inventory["issues"])


def test_unrecorded_resource_is_not_silently_accepted(local_wheel):
    from qf import native_catalog

    sdk_root, _ = local_wheel
    (sdk_root / "web/unexpected.js").write_text("unexpected", encoding="utf-8")
    inventory = native_catalog.inspect_installation()
    assert inventory["ready"] is False
    assert any("unexpected.js" in issue for issue in inventory["issues"])


@pytest.mark.parametrize("relative_name", [
    "../__init__.py", "tutorial/../../__init__.py", "/tmp/demo.py",
    "C:/demo.py", "tutorial\\demo.py", "tutorial/../tutorial/demo.py", "__init__.py",
    "tutorial/unknown.py",
])
def test_example_reader_rejects_paths_outside_inventory(local_wheel, relative_name):
    from qf import native_catalog

    with pytest.raises(ValueError):
        native_catalog.read_example(relative_name)


def test_example_reader_returns_source_without_executing(local_wheel, monkeypatch):
    from qf import native_catalog

    def forbidden(*args, **kwargs):
        pytest.fail("读取示例不得创建 TqApi 会话")

    monkeypatch.setattr(tqsdk.TqApi, "__init__", forbidden)
    source = native_catalog.read_example("tutorial/demo.py")
    assert source == "raise RuntimeError('example must never run')\n"


def test_permissions_and_boundaries_are_visible():
    from qf import native_catalog

    inventory = native_catalog.inspect_installation()
    capabilities = {item["key"]: item for item in inventory["capabilities"]}
    required = {
        "market_data", "indicators", "backtest", "quick_simulation", "target_position",
        "scheduler", "algorithm", "downloader", "scenario", "reporting", "notifications",
        "risk_rules", "multi_account", "direct_accounts", "stock_accounts", "examples",
        "channels", "trading_status", "extended_data",
    }
    assert capabilities.keys() >= required
    for capability in capabilities.values():
        assert {"key", "title", "description", "doc", "installed", "integration", "permission"} <= (
            capability.keys()
        )
        assert isinstance(capability["installed"], bool)
        assert urlparse(capability["doc"]).hostname in {"doc.shinnytech.com", "www.shinnytech.com"}
    assert "tq_dl" in capabilities["downloader"]["permission"]
    assert capabilities["downloader"]["doc"].endswith("reference/tqsdk.tools.download.html")
    assert "专业" in capabilities["downloader"]["permission"]
    assert "tq_lc_rk" in capabilities["risk_rules"]["permission"]
    assert "专业" in capabilities["risk_rules"]["permission"]
    assert "企业" in capabilities["direct_accounts"]["permission"]
    assert "tq_trading_status" in capabilities["trading_status"]["permission"]
    assert "不支持回测" in capabilities["trading_status"]["description"]
    assert "专业" in capabilities["extended_data"]["permission"]
    assert "不支持回测" in capabilities["algorithm"]["description"]
    assert "期货" in capabilities["scenario"]["description"]
    assert "单账户" in capabilities["scenario"]["description"]
    assert "短信" in capabilities["notifications"]["description"]
    assert "邮件" in capabilities["notifications"]["description"]
    assert "账户" in capabilities["multi_account"]["permission"]
    assert "免费" in capabilities["market_data"]["permission"]
    assert "核验" in capabilities["market_data"]["permission"]
    assert "过期" in capabilities["examples"]["description"]
    assert "占位" in capabilities["examples"]["description"]
    assert "只读" in capabilities["examples"]["description"]


def test_missing_sdk_symbol_is_reported(monkeypatch):
    from qf import native_catalog

    monkeypatch.delattr(tqsdk, "TargetPosScheduler")
    inventory = native_catalog.inspect_installation()
    scheduler = next(item for item in inventory["capabilities"] if item["key"] == "scheduler")
    assert scheduler["installed"] is False
    assert inventory["ready"] is False
    assert any("TargetPosScheduler" in issue for issue in inventory["issues"])


def test_skill_and_extra_dependency_have_inspectable_status():
    from qf import native_catalog

    inventory = native_catalog.inspect_installation()
    skill = inventory["skill"]
    assert isinstance(skill["root"], str)
    assert skill["installed"] is True
    assert len(skill["files"]) == 14
    assert skill["missing"] == []
    assert "SKILL.md" in skill["files"]
    dependency = inventory["example_dependencies"]["sklearn"]
    assert isinstance(dependency["installed"], bool)
    assert isinstance(dependency["version"], str)
    if not dependency["installed"]:
        assert any("scikit-learn" in issue for issue in inventory["issues"])


def test_inventory_script_runs_in_isolated_interpreter():
    script = Path(__file__).resolve().parents[1] / "tools/native_inventory.py"
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(script)], capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )
    inventory = json.loads(result.stdout)
    assert result.returncode == (1 if inventory["issues"] else 0)
    assert result.stderr == ""
