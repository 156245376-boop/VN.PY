"""价格范围和画图模式的离线行为回归，不连接账户。"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_native_chart_tools():
    node = shutil.which("node")
    if node is None:
        pytest.skip("未安装 Node")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/native_tools_node.js")], cwd=root,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_TOOLS_OFFLINE_OK" in result.stdout


def test_native_chart_tools_in_real_webview():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("native_tools_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_TOOLS_SMOKE=" in result.stdout
