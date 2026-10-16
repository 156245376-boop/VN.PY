"""离线核对 TqSdk 原生能力、官方示例、图形资源与技能，不创建 API 会话。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qf.native_catalog import inspect_installation  # noqa: E402


def main() -> int:
    inventory = inspect_installation()
    # 维持 UTF-8 JSON 输出，也适用于 Windows 控制台和重定向。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    return 1 if inventory["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
