"""独立工作台入口：隔离环境后打开可信 WebView2 页面。"""

import multiprocessing
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "TQ_ACTION", "TQ_AUTH",
             "TQ_HTTP_SERVER_ADDRESS", "TQ_BROKER_ID", "TQ_ACCOUNT_ID", "TQ_PASSWORD", "TQ_USER",
             "TQ_INIT_BALANCE", "TQ_START_DT", "TQ_END_DT"):
    os.environ.pop(name, None)
os.environ["UV_PROJECT_ENVIRONMENT"] = str(ROOT / ".venv-tqsdk")

from tools.environment_probe import verify_environment  # noqa: E402

if __name__ == "__main__":
    try:
        multiprocessing.freeze_support()
        verify_environment(ROOT / ".venv-tqsdk")
        from qf.workbench import main
        main()
    except Exception:
        import tkinter as tk
        import tkinter.messagebox as messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror(
            "天勤工作台启动未完成",
            "请运行 tools/setup.ps1 和 tools/check.ps1 核对本机环境。\n"
            "独立窗口还需要 Microsoft Edge WebView2 运行时：\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n"
            "原研究入口保留在 tools/gui_entry.py。凭证不要发到聊天或报错记录。",
        )
        window.destroy()
        raise SystemExit(1) from None
