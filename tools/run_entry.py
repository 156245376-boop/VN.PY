"""由隔离解释器启动，只加入当前仓库应用路径。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qf.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
