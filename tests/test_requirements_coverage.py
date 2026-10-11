"""验收标准覆盖报告的可靠性测试(R34.12)。"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.requirements_coverage import (
    CROSS_CUTTING_REQUIREMENTS,
    MODULE_REQUIREMENTS,
    build_report,
    collect_coverage,
    criteria_for_module,
    parse_requirements,
)

pytestmark = pytest.mark.covers("R34.12")


def test_requirements_parser_finds_all_sections_and_criteria() -> None:
    text = """### Requirement 1: 示例\n\n#### Acceptance Criteria\n\n1. 第一条\n2. 第二条\n"""
    assert parse_requirements(text) == {"R1.1": "第一条", "R1.2": "第二条"}


def test_coverage_requires_explicit_literal_marker(tmp_path: Path) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        "import pytest\n"
        "pytestmark = pytest.mark.covers('R1.1', 'R2.3')\n"
        "def test_text_only():\n"
        "    note = 'R9.9'\n",
        encoding="utf-8",
    )
    covered, errors = collect_coverage([test_file])
    assert covered == {"R1.1", "R2.3"}
    assert errors == []


def test_invalid_coverage_marker_is_reported(tmp_path: Path) -> None:
    test_file = tmp_path / "test_invalid.py"
    test_file.write_text(
        "import pytest\npytestmark = pytest.mark.covers('Requirement 1')\n",
        encoding="utf-8",
    )
    covered, errors = collect_coverage([test_file])
    assert covered == set()
    assert errors and "非法验收标准编号" in errors[0]


def test_module_mapping_includes_owned_and_cross_cutting_requirements() -> None:
    criteria = {
        "R3.1": "meta",
        "R24.1": "all modules",
        "R27.1": "meta",
        "R34.1": "all modules",
        "R1.1": "gateway",
    }
    assert criteria_for_module(criteria, "meta") == {
        "R3.1": "meta",
        "R24.1": "all modules",
        "R27.1": "meta",
        "R34.1": "all modules",
    }
    assert {24, 26, 34} == CROSS_CUTTING_REQUIREMENTS
    assert set(MODULE_REQUIREMENTS) == {
        "apps",
        "config",
        "core",
        "costs",
        "data",
        "engines",
        "execution",
        "gateway",
        "indicators",
        "meta",
        "obs",
        "risk",
        "runtime",
        "strategy",
    }


def test_current_report_is_honest_about_covered_and_missing_items() -> None:
    missing, errors = build_report("core")
    assert errors == []
    assert not any(line.startswith("R33.1 ") for line in missing)
    assert any(line.startswith("R33.4 ") for line in missing)
