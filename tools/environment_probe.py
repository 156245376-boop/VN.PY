"""只验证解释器及 SDK 身份，不创建账户或 API 会话。"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.metadata
import io
import json
import platform
import site
import sys
from pathlib import Path


class EnvironmentCheckError(RuntimeError):
    """当前解释器或 SDK 不符合项目约束。"""


def verify_environment(expected_environment: Path) -> dict[str, str]:
    """检查真实运行环境，拒绝旧环境、路径遮蔽与错误 SDK 版本。"""
    expected = expected_environment.resolve()
    if sys.version_info[:3] != (3, 13, 11):
        raise EnvironmentCheckError("Python 3.13.11 is required")
    if not sys.flags.isolated or site.ENABLE_USER_SITE is not False:
        raise EnvironmentCheckError("Run this check with Python -I")
    if Path(sys.prefix).resolve() != expected or sys.prefix == sys.base_prefix:
        raise EnvironmentCheckError("Incorrect virtual environment")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sdk = importlib.import_module("tqsdk")
        for name in ("numpy", "pandas", "scipy"):
            importlib.import_module(name)
        for name in ("TqApi", "TqAuth", "TqSim", "TargetPosTask"):
            if not hasattr(sdk, name):
                raise EnvironmentCheckError(f"Missing SDK interface: {name}")
    version = importlib.metadata.version("tqsdk")
    if version != "3.10.2":
        raise EnvironmentCheckError("TqSdk 3.10.2 is required")
    module_path = Path(sdk.__file__).resolve()
    if not module_path.is_relative_to(expected):
        raise EnvironmentCheckError("SDK was imported outside the project environment")
    return {
        "python": platform.python_version(), "executable": sys.executable,
        "tqsdk": version, "module_path": str(module_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-environment", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps({"status": "ready", **verify_environment(args.expected_environment)}))
        return 0
    except (EnvironmentCheckError, ImportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
