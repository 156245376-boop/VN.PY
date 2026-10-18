import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('script', ['indicator_state_node.js'])
def test_indicator_javascript_behaviors(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name(script))],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_chart_pane_message_identity_and_lifecycle():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_workspace_node.js'))],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_WORKSPACE_OK' in result.stdout


def test_layout_saves_are_serial_and_only_latest_is_confirmed():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_save_node.js'))],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_SAVE_OK' in result.stdout


def test_rejected_request_retains_layout_and_last_successful_selection():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_controller_node.js'))],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_CONTROLLER_OK' in result.stdout
