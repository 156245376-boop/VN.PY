"""需求编号的唯一性与连续性(R34.12 的前提)。

R34.12 要求「输出目标 Module_Package 所对应需求中尚无测试覆盖的验收标准条目清单」。
这项追溯以 `R<需求>.<条目>` 为键 —— **编号重复会使两条不同的验收标准共享一个键,
编号缺号会使清单里出现指向不存在条目的引用。** 两种情况下覆盖率报表都会静默出错。

代码注释与 ADR 同样以该形式引用需求(见 docs/adr/INDEX.md 第 10 行的约定),
故编号一旦重复,引用就失去唯一指向。

本文件属 ADR-0001 分级中的第一级(确定性检查):可由脚本判定,无假阴性,秒级重跑。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / ".kiro" / "specs" / "vnpy-futures-trading-system" / "requirements.md"

_SECTION = re.compile(r"^###\s+Requirement\s+(\d+):\s*(.+)$")
_AC_HEADING = re.compile(r"^####\s+Acceptance Criteria\s*$")
_AC_ITEM = re.compile(r"^(\d+)\.\s+\S")


def _parse() -> list[tuple[int, str, list[int]]]:
    """解析出 [(需求编号, 标题, [验收标准编号...])]。

    只采集「#### Acceptance Criteria」标题之后、下一个 `###` 之前的顶层有序列表项。
    """
    sections: list[tuple[int, str, list[int]]] = []
    number = 0
    title = ""
    items: list[int] = []
    in_ac = False

    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if match := _SECTION.match(line):
            if number:
                sections.append((number, title, items))
            number, title, items, in_ac = int(match.group(1)), match.group(2).strip(), [], False
            continue
        if _AC_HEADING.match(line):
            in_ac = True
            continue
        if in_ac and (match := _AC_ITEM.match(line)):
            items.append(int(match.group(1)))

    if number:
        sections.append((number, title, items))
    return sections


def test_requirements_file_exists() -> None:
    """需求文档是本项目的真相来源,缺失即无从校验其余一切。"""
    assert REQUIREMENTS.exists(), f"未找到需求文档:{REQUIREMENTS}"


def test_requirement_sections_are_sequential() -> None:
    """Requirement 编号须从 1 开始连续且不重复。"""
    numbers = [n for n, _, _ in _parse()]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"Requirement 编号不连续或重复。实际:{numbers}"
    )


def test_every_requirement_has_criteria() -> None:
    """每条需求都须有验收标准 —— 没有验收标准的需求不可测,也无法被覆盖检查追溯。"""
    empty = [f"R{n}({t})" for n, t, items in _parse() if not items]
    assert not empty, f"以下需求没有验收标准条目:{empty}"


def test_acceptance_criteria_are_sequential() -> None:
    """验收标准编号须在各自需求内从 1 开始连续且不重复。

    失败信息直接给出重复号与缺号,便于定位 —— 这类缺陷在 736 行文档里肉眼很难发现。
    """
    problems: list[str] = []
    for number, title, items in _parse():
        expected = list(range(1, len(items) + 1))
        if items == expected:
            continue
        duplicated = sorted({i for i in items if items.count(i) > 1})
        missing = sorted(set(expected) - set(items))
        detail = []
        if duplicated:
            detail.append(f"重复号 {duplicated}")
        if missing:
            detail.append(f"缺号 {missing}")
        problems.append(
            f"R{number}({title}):共 {len(items)} 条,{'、'.join(detail) or '顺序错乱'}\n"
            f"    实际编号:{items}"
        )

    assert not problems, (
        "验收标准编号存在缺陷,会使 R34.12 的覆盖检查与代码注释里的 R<n>.<m> "
        "引用失去唯一指向:\n" + "\n".join(problems)
    )
