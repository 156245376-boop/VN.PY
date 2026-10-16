"""独立 pythonw 入口；先隔离环境并验证，再打开本机窗口。"""

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
        verify_environment(ROOT / ".venv-tqsdk")
        from qf.gui import main
        main()
    except Exception:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("天勤工作台启动失败", "请检查 .venv-tqsdk 环境和项目文件。\n"
                             + "安装入口为 tools/setup.ps1；不要输入凭证到报错信息中。")
        window.destroy()
