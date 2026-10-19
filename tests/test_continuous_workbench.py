import subprocess
import sys
from pathlib import Path


def test_continuous_years_flow_and_offline_reopen_in_webview(tmp_path):
    for phase in ('write', 'reopen'):
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
            str(Path(__file__).with_name('continuous_workbench_smoke.py')), str(tmp_path), phase],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=100)
        assert result.returncode == 0, result.stdout+result.stderr
        assert 'CONTINUOUS_WORKBENCH_OK' in result.stdout
