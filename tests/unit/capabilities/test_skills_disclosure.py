"""渐进披露（INSTRUCTIONS/RESOURCES）的判红用例（C06，TDD）。

真源：`docs/plan/05` T8；改造 crewAI `skills/parser.py` 的三级披露 + `_MAX_BODY_CHARS` 告警。
用 tmp_path 真文件；大正文只告警不失败（防 prompt 膨胀），升 idempotent。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from questor.capabilities.skills.disclosure import _MAX_BODY_CHARS, load_skill_instructions, load_skill_resources
from questor.capabilities.skills.loader import discover_skills
from questor.capabilities.skills.models import DisclosureLevel


def _skill(tmp_path: Path, name: str, body: str):
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}", encoding="utf-8")
    return discover_skills(tmp_path)[0]


def test_instructions_level_loads_body(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "s1", "# hello body")
    assert skill.body is None and skill.disclosure_level is DisclosureLevel.METADATA
    loaded = load_skill_instructions(skill)
    assert loaded.body == "# hello body"
    assert loaded.disclosure_level is DisclosureLevel.INSTRUCTIONS


def test_instructions_is_idempotent(tmp_path: Path) -> None:
    skill = load_skill_instructions(_skill(tmp_path, "s2", "x"))
    again = load_skill_instructions(skill)
    assert again is skill  # 已 >= INSTRUCTIONS 直接返回原对象


def test_oversized_body_warns_but_still_loads(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    big = "z" * (_MAX_BODY_CHARS + 10)
    with caplog.at_level(logging.WARNING, logger="questor.skills"):
        loaded = load_skill_instructions(_skill(tmp_path, "big", big))
    assert loaded.disclosure_level is DisclosureLevel.INSTRUCTIONS  # 不失败
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.skills"]
    assert any("big" in m for m in warns)  # 但出声（防 prompt 膨胀）


def test_resources_level_lists_files_and_promotes_instructions(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "s3", "body")
    scripts = skill.path / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("print(1)", encoding="utf-8")
    loaded = load_skill_resources(skill)
    assert loaded.disclosure_level is DisclosureLevel.RESOURCES
    assert "scripts/run.py" in loaded.resources or "scripts\\run.py" in loaded.resources
    assert loaded.body == "body"  # 升 RESOURCES 时把 INSTRUCTIONS 也补齐
