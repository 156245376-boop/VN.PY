import subprocess
import sys
from pathlib import Path


def test_complete_research_window_in_real_webview():
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-X', 'utf8',
         str(Path(__file__).with_name('research_window_smoke.py'))],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'RESEARCH_WINDOW_OK' in result.stdout
