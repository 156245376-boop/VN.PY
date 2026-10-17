"""原生图表历史适配的 Node 离线回归；不创建账户或网络连接。"""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_native_history_uses_real_sdk_offline():
    node = shutil.which("node")
    if node is None:
        pytest.skip("未安装 Node，跳过原生 JavaScript 离线检查")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/native_history_node.js")],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_HISTORY_OFFLINE_OK" in result.stdout
