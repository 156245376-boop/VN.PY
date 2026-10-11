"""输出 Module_Package 尚无测试覆盖的验收标准清单(R34.12)。

覆盖关系只认 pytest 的显式 `@pytest.mark.covers("R<n>.<m>")` 标记。不得从测试名、
docstring 或注释猜测,否则报告会产生虚假绿色。需求可属于多个模块;横切契约重复出现是刻意的。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / ".kiro" / "specs" / "vnpy-futures-trading-system" / "requirements.md"
TESTS = ROOT / "tests"

# 依据 CLAUDE.md 的模块职责与 IMPLEMENTATION_PLAN.md 的阶段对应表维护。
# R24/R26/R34 是每个模块都须遵守的横切契约;领域需求允许重复归属。
CROSS_CUTTING_REQUIREMENTS = frozenset({24, 26, 34})
MODULE_REQUIREMENTS: dict[str, frozenset[int]] = {
    "apps": frozenset({20, 21, 23}),
    "config": frozenset({22}),
    "core": frozenset({32, 33}),
    "costs": frozenset({29}),
    "data": frozenset({4, 5, 6, 7, 8, 9, 10, 25, 28}),
    "engines": frozenset({12, 13, 14, 15, 33}),
    "execution": frozenset({17, 29}),
    "gateway": frozenset({1, 2, 30}),
    "indicators": frozenset({33}),
    "meta": frozenset({3, 27, 30}),
    "obs": frozenset({20, 21}),
    "risk": frozenset({19}),
    "runtime": frozenset({16, 18, 31, 32}),
    "strategy": frozenset({11, 33}),
}

_SECTION = re.compile(r"^###\s+Requirement\s+(\d+):\s*(.+)$")
_CRITERION = re.compile(r"^(\d+)\.\s+(.+)$")
_CRITERION_ID = re.compile(r"^R([1-9]\d*)\.([1-9]\d*)$")


def parse_requirements(text: str) -> dict[str, str]:
    """返回验收标准编号到原文的映射。"""
    result: dict[str, str] = {}
    requirement = 0
    in_criteria = False
    for line in text.splitlines():
        if match := _SECTION.match(line):
            requirement = int(match.group(1))
            in_criteria = False
        elif line == "#### Acceptance Criteria":
            in_criteria = True
        elif line.startswith("### "):
            in_criteria = False
        elif in_criteria and (match := _CRITERION.match(line)):
            key = f"R{requirement}.{int(match.group(1))}"
            if key in result:
                raise ValueError(f"验收标准编号重复:{key}")
            result[key] = match.group(2).strip()
    return result


def _is_mark_call(node: ast.AST, name: str) -> TypeGuard[ast.Call]:
    """判定 `pytest.mark.<name>(...)` 调用。"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "mark"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "pytest"
    )


def _calls(tree: ast.AST) -> Iterable[ast.Call]:
    for node in ast.walk(tree):
        if _is_mark_call(node, "covers"):
            yield node


def _pending_ranges(tree: ast.Module) -> tuple[list[tuple[int, int]], bool]:
    """返回 (待填用例的行区间, 整个模块是否待填)。

    待填用例的 `covers` 声明**必须无效**:它当前的执行结果是失败,把失败的用例
    算成已覆盖,正是 R34.12 这份报告要防的假绿。
    """
    ranges: list[tuple[int, int]] = []
    module_pending = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                values = node.value.elts
            else:
                values = [node.value]
            module_pending = module_pending or any(
                _is_mark_call(value, "pending_expected") for value in values
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [d for d in node.decorator_list if _is_mark_call(d, "pending_expected")]
            if decorators:
                start = min(d.lineno for d in decorators)
                ranges.append((start, node.end_lineno or node.lineno))
    return ranges, module_pending


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def collect_coverage(paths: Iterable[Path]) -> tuple[set[str], list[str]]:
    """读取 covers 标记,并返回覆盖编号与标记格式错误。"""
    covered: set[str] = set()
    errors: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        display_path = _display_path(path)
        pending_ranges, module_pending = _pending_ranges(tree)
        for call in _calls(tree):
            if module_pending or any(start <= call.lineno <= end for start, end in pending_ranges):
                errors.append(
                    f"{display_path}:{call.lineno}: pending_expected 用例不得声明 covers —— "
                    f"它的执行结果是失败,算作已覆盖会造出未核对却显示为绿的假象(R34.7)"
                )
                continue
            if not call.args:
                errors.append(f"{display_path}:{call.lineno}: covers 标记不能为空")
            for argument in call.args:
                if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                    errors.append(
                        f"{display_path}:{call.lineno}: covers 参数必须是字符串字面量"
                    )
                    continue
                criterion = argument.value
                if not _CRITERION_ID.fullmatch(criterion):
                    errors.append(
                        f"{display_path}:{call.lineno}: 非法验收标准编号 {criterion!r}"
                    )
                    continue
                covered.add(criterion)
    return covered, errors


def criteria_for_module(criteria: dict[str, str], module: str) -> dict[str, str]:
    requirements = MODULE_REQUIREMENTS[module] | CROSS_CUTTING_REQUIREMENTS
    return {
        key: text
        for key, text in criteria.items()
        if int(key[1 : key.index(".")]) in requirements
    }


def build_report(module: str | None) -> tuple[list[str], list[str]]:
    criteria = parse_requirements(REQUIREMENTS.read_text(encoding="utf-8"))
    covered, errors = collect_coverage(sorted(TESTS.glob("**/test_*.py")))
    unknown = sorted(covered - criteria.keys())
    errors.extend(f"covers 标记引用不存在的验收标准:{key}" for key in unknown)

    scope = criteria if module is None else criteria_for_module(criteria, module)
    missing = [key for key in scope if key not in covered]
    lines = [f"{key} {scope[key]}" for key in missing]
    return lines, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--module",
        choices=sorted(MODULE_REQUIREMENTS),
        help="只报告指定 Module_Package;省略则报告全部需求",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="只输出条数,不逐条列出 —— 供自动化门禁调用,避免日志被缺口清单淹没",
    )
    args = parser.parse_args(argv)
    missing, errors = build_report(args.module)

    if errors:
        print("覆盖标记无效:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    scope = args.module or "全部模块"
    print(f"{scope}: {len(missing)} 条验收标准尚无显式测试覆盖")
    if not args.summary:
        for line in missing:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
