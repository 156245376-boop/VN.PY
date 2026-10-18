import shutil
import subprocess
from pathlib import Path

import pytest


def test_chart_drawings_version_and_isolation():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('chart_drawings_node.js'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CHART_DRAWINGS_OK' in result.stdout
