"""天勤原生图表右上角工具栏固定，真实 WebView2 离线验收。"""

import subprocess
import sys
from pathlib import Path


def test_native_toolbar_pinned_in_real_webview():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8",
         str(Path(__file__).with_name("native_toolbar_smoke.py"))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_TOOLBAR_OK=" in result.stdout
