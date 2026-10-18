import shutil
import subprocess
from pathlib import Path

import pytest


def test_research_form_node():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name('research_form_node.js'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'RESEARCH_FORM_OK' in result.stdout
