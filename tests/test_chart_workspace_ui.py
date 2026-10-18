import shutil
import subprocess
from pathlib import Path

import pytest


def test_chart_pane_message_identity_and_lifecycle():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_workspace_node.js'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_WORKSPACE_OK' in result.stdout


def test_layout_saves_are_serial_and_only_latest_is_confirmed():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_save_node.js'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_SAVE_OK' in result.stdout
