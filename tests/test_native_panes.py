import subprocess
import sys
from pathlib import Path


def test_native_panes():
    result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                             str(Path(__file__).with_name('native_panes_smoke.py'))],
                            capture_output=True, text=True, encoding='utf-8', timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'NATIVE_PANES_OK' in result.stdout
