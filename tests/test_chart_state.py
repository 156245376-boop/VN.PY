import shutil
import subprocess
from pathlib import Path

import pytest


def test_chart_state():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_state_node.js'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_STATE_OK' in result.stdout
