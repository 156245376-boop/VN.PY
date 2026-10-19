import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('script,marker', [('research_form_node.js', 'RESEARCH_FORM_OK'),
    ('pivot_form_node.js', 'PIVOT_FORM_OK'),
    ('research_terminal_node.js', 'RESEARCH_TERMINAL_OK'),
    ('live_research_render_node.js', 'LIVE_RESEARCH_RENDER_OK'),
    ('replay_render_node.js', 'REPLAY_RENDER_OK'),
    ('research_results_node.js', 'RESEARCH_RESULTS_OK')])
def test_research_form_node(script, marker):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node missing')
    result = subprocess.run([node, str(Path(__file__).with_name(script))],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
