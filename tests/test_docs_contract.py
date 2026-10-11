"""文档不说谎的机械手段(R26.2/R26.6/R26.7)。

**说谎的文档比没有文档更糟** —— 未来的模型会信它。本文件承担三项可自动判定的
检查,属 ADR-0001 分级中的第一级(确定性检查):README 固定小节完整且顺序一致、
「公开接口」小节等于 `__all__`、全部 ADR 引用均指向已登记的记录。

这些检查便宜且无假阴性。文档中「为什么」类内容的真实性无法机械判定,不在此列。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ADR_DIR = ROOT / "docs" / "adr"
README_SECTIONS = [
    "## 职责",
    "## 公开接口",
    "## 不变式",
    "## 禁止 import",
    "## 为什么这么设计",
    "## 否决过的方案",
    "## 已知局限",
    "## 测试",
]

pytestmark = pytest.mark.covers("R26.6", "R26.7")

#: 「公开接口」小节中的条目形如 "- `Name`"。小节内的说明性文字不以 "- " 开头,
#: 故不会被误取。
_BULLET = re.compile(r"^-\s+`([^`]+)`")

#: 引用形式统一为 ADR-XXXX(INDEX.md 第 10 行规定)。
_ADR_REF = re.compile(r"ADR-(\d{4})")

#: INDEX.md「待补记录」表的行首编号。
_ADR_PLANNED = re.compile(r"^\|\s*(\d{4})\s*\|")


def _module_names() -> list[str]:
    return sorted(p.name for p in SRC.iterdir() if (p / "__init__.py").exists())


def _declared_api(readme: Path) -> list[str]:
    """取出 README「公开接口」小节列出的名字。"""
    lines = readme.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## 公开接口")
    except ValueError:
        pytest.fail(f"{readme.relative_to(ROOT)} 缺少「## 公开接口」小节(R26.2 要求小节顺序固定)")
    names: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if match := _BULLET.match(line.strip()):
            names.append(match.group(1))
    return names


@pytest.mark.parametrize("module", _module_names())
def test_readme_exists(module: str) -> None:
    """每个 Module_Package 都须有说明文档(R26.2)。"""
    assert (SRC / module / "README.md").exists(), (
        f"src/{module}/ 缺少 README.md。这才是「只改一个模块」真正的实现机制 —— "
        f"没有它,修改本模块的人必须读完全部实现文件才能知道不变式是什么"
    )


@pytest.mark.parametrize("module", _module_names())
def test_readme_sections_are_complete_and_ordered(module: str) -> None:
    """固定小节顺序使局部契约可预测;内容完整性仍在对应 Phase 验收(R26.2)。"""
    readme = SRC / module / "README.md"
    headings = [
        line
        for line in readme.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert headings == README_SECTIONS, (
        f"{readme.relative_to(ROOT)} 的小节不完整或顺序错误。\n"
        f"  期望:{README_SECTIONS}\n"
        f"  实际:{headings}"
    )


@pytest.mark.parametrize("module", _module_names())
def test_readme_api_matches_all(module: str) -> None:
    """README 的公开接口清单须与 `__all__` 完全一致(R26.6)。

    这条是文档不说谎的最低保证:至少在「本模块对外提供什么」这件事上不撒谎。
    """
    declared = _declared_api(SRC / module / "README.md")
    actual = list(importlib.import_module(module).__all__)

    missing = sorted(set(actual) - set(declared))
    extra = sorted(set(declared) - set(actual))
    assert not missing and not extra, (
        f"src/{module}/README.md 的「公开接口」与 {module}.__all__ 不一致。\n"
        f"  README 缺少:{missing or '无'}\n"
        f"  README 多出:{extra or '无'}\n"
        f"R26.8 要求接口变更与文档更新在同一个 commit 内完成。"
    )


def _written_adrs() -> set[str]:
    """已写成记录的 ADR 编号。"""
    numbers: set[str] = set()
    for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"):
        if match := re.match(r"(\d{4})", path.name):
            numbers.add(match.group(1))
    return numbers


def _planned_adrs(text: str) -> set[str]:
    """取「待补记录」表登记的编号。

    「记录清单」表的行以 markdown 链接起头(`| [0001](...)`),不匹配本模式,
    故传入整份 INDEX 也只会取到待补项。
    """
    return {m.group(1) for line in text.splitlines() if (m := _ADR_PLANNED.match(line.strip()))}


def _docs_and_sources() -> list[Path]:
    """须扫描 ADR 引用的文件:根目录与 docs/ 的 Markdown,加 src/ 的文档与源码。"""
    return [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/**/*.md"),
        *SRC.glob("**/*.md"),
        *SRC.glob("**/*.py"),
    ]


def test_no_dangling_adr_reference() -> None:
    """全部 ADR 引用须指向已存在或已登记待补的记录(R26.7)。

    「已登记待补」是合法引用:多条承重决策按计划在对应 Phase 落地时才写成记录
    (决策当时的约束与否决理由,事后补写不出来),但设计文档现在就需要指向它们。
    INDEX.md 的「待补记录」表正是为此存在。
    """
    index = ADR_DIR / "INDEX.md"
    assert index.exists(), "docs/adr/INDEX.md 缺失"

    known = _written_adrs() | _planned_adrs(index.read_text(encoding="utf-8"))

    dangling: dict[str, set[str]] = {}
    for path in _docs_and_sources():
        refs = {m.group(1) for m in _ADR_REF.finditer(path.read_text(encoding="utf-8"))}
        if bad := refs - known:
            dangling[str(path.relative_to(ROOT))] = bad

    assert not dangling, (
        "存在指向不存在记录的 ADR 引用:\n"
        + "\n".join(f"  {p}: {sorted(v)}" for p, v in sorted(dangling.items()))
        + "\n新增引用时须同时在 docs/adr/INDEX.md 登记(已写成记录或列入待补)。"
    )


def test_planned_adr_not_yet_written() -> None:
    """INDEX 的「待补记录」表不得列入已写成的记录 —— 否则 INDEX 本身就在说谎。"""
    index = ADR_DIR / "INDEX.md"
    text = index.read_text(encoding="utf-8")
    pending_section = text.split("## 待补记录", 1)
    assert len(pending_section) == 2, "docs/adr/INDEX.md 缺少「## 待补记录」小节"

    stale = sorted(_planned_adrs(pending_section[1]) & _written_adrs())
    assert not stale, (
        f"以下 ADR 已写成记录,但仍留在 INDEX.md 的「待补记录」表中:{stale}\n"
        f"应将其移入「记录清单」表。"
    )
