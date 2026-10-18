import subprocess
import sys
from pathlib import Path


def test_native_panes():
    target = Path(__file__).parents[1] / '.superpowers/panes-fixture-output.txt'
    target.parent.mkdir(exist_ok=True)
    with target.open(mode='w+', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                                 str(Path(__file__).with_name('native_panes_smoke.py'))],
                                stdout=log, stderr=subprocess.STDOUT, timeout=50)
        log.seek(0)
        output = log.read()
    assert result.returncode == 0, output
    assert 'NATIVE_PANES_OK' in output
