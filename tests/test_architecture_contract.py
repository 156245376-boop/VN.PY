"""可由脚本确定的架构不变式(R24.4/R24.10/R24.11/R33.2)。

这些检查只判断语法事实,不判断领域规则。它们属于 ADR-0001 的第一级防线:
无外部依赖、无模型判断、每次变更都可重复执行。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
MAX_SOURCE_LINES = 400

pytestmark = pytest.mark.covers("R24.4", "R24.11", "R33.2")


def _packages() -> set[str]:
    return {path.name for path in SRC.iterdir() if (path / "__init__.py").exists()}


def _source_files() -> list[Path]:
    return sorted(SRC.glob("**/*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_source_files_do_not_exceed_400_lines() -> None:
    """文件大小纪律必须在第一次越界时失败,而不是靠审阅者肉眼发现。"""
    oversized = []
    for path in _source_files():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_SOURCE_LINES:
            oversized.append(f"{path.relative_to(ROOT)}: {line_count} 行")
    assert not oversized, "单个源文件超过 400 行(R24.11):\n  " + "\n  ".join(oversized)


def _literal_all(package: str) -> set[str]:
    tree = _tree(SRC / package / "__init__.py")
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            names = {
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            if len(names) == len(value.elts):
                return names
    raise AssertionError(f"src/{package}/__init__.py 的 __all__ 必须是字符串字面量集合")


def test_cross_package_imports_use_public_facade() -> None:
    """跨包只允许 `from package import PublicName`,且名称须属于 `__all__`。"""
    packages = _packages()
    public_names = {package: _literal_all(package) for package in packages}
    violations: list[str] = []

    for path in _source_files():
        source_package = path.relative_to(SRC).parts[0]
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name.split(".", 1)[0]
                    if target in packages and target != source_package:
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: import {alias.name}; "
                            f"跨包请使用 from {target} import <公开名>"
                        )
                continue
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            target = node.module.split(".", 1)[0]
            if target not in packages or target == source_package:
                continue
            if node.module != target:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: from {node.module} import ...; "
                    f"应改为从 {target} 的公开接口导入"
                )
                continue
            invalid = sorted(
                alias.name for alias in node.names if alias.name not in public_names[target]
            )
            if invalid:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: {target} 未公开 {invalid}"
                )

    assert not violations, "跨 Module_Package 绕过了公开接口(R24.4):\n  " + "\n  ".join(
        violations
    )


_CLOCK_METHODS = {"now", "today", "utcnow"}
_TIME_FUNCTIONS = {
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "perf_counter_ns",
}


def _system_clock_calls(tree: ast.Module) -> list[tuple[int, str]]:
    datetime_modules: set[str] = set()
    datetime_classes: set[str] = set()
    time_modules: set[str] = set()
    time_functions: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "datetime":
                    datetime_modules.add(local)
                elif alias.name == "time":
                    time_modules.add(local)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "datetime":
                for alias in node.names:
                    if alias.name in {"date", "datetime"}:
                        datetime_classes.add(alias.asname or alias.name)
            elif node.module == "time":
                for alias in node.names:
                    if alias.name in _TIME_FUNCTIONS:
                        time_functions.add(alias.asname or alias.name)

    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in time_functions:
            calls.append((node.lineno, func.id))
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                owner = func.value.id
                is_datetime_call = owner in datetime_classes and func.attr in _CLOCK_METHODS
                is_time_call = owner in time_modules and func.attr in _TIME_FUNCTIONS
                if is_datetime_call or is_time_call:
                    calls.append((node.lineno, f"{owner}.{func.attr}"))
            elif isinstance(func.value, ast.Attribute):
                parent = func.value
                if (
                    isinstance(parent.value, ast.Name)
                    and parent.value.id in datetime_modules
                    and parent.attr in {"date", "datetime"}
                    and func.attr in _CLOCK_METHODS
                ):
                    calls.append(
                        (node.lineno, f"{parent.value.id}.{parent.attr}.{func.attr}")
                    )
    return calls


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from datetime import datetime\ndatetime.now()", "datetime.now"),
        ("import datetime as dt\ndt.datetime.now()", "dt.datetime.now"),
        ("from time import time as wall_clock\nwall_clock()", "wall_clock"),
        ("def f():\n    from datetime import date as Day\n    return Day.today()", "Day.today"),
    ],
)
def test_system_clock_guard_recognizes_aliases_and_local_imports(
    source: str, expected: str
) -> None:
    calls = _system_clock_calls(ast.parse(source))
    assert any(call == expected for _, call in calls)


def test_system_clock_guard_ignores_datetime_construction() -> None:
    tree = ast.parse("from datetime import datetime\ndatetime(2024, 1, 1)")
    assert _system_clock_calls(tree) == []


def test_only_timeutil_reads_the_system_clock() -> None:
    """别名导入也必须被识别,避免规则只能拦住一种拼写。"""
    allowed = SRC / "core" / "timeutil.py"
    violations = [
        f"{path.relative_to(ROOT)}:{line}: {call}()"
        for path in _source_files()
        if path != allowed
        for line, call in _system_clock_calls(_tree(path))
    ]
    assert not violations, "core/timeutil.py 之外调用了系统时钟(R33.2):\n  " + "\n  ".join(
        violations
    )
