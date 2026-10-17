"""SKILL.md frontmatter 校验的判红用例（C04，TDD）。

真源：`docs/plan/05` T8；改造 crewAI `skills/validation.py:13-56`（name 正则 + 目录名==声明名）。
fail-closed：缺必填/名字非法/类型非 str 一律抛，坏文件由 loader 逐文件降级出声（C6）。"""

from __future__ import annotations

import pytest

from questor.capabilities.skills.models import SkillFrontmatter
from questor.capabilities.skills.parser import SkillParseError
from questor.capabilities.skills.validation import validate_directory_name, validate_frontmatter


def test_builds_frontmatter_from_valid_mapping() -> None:
    fm = validate_frontmatter({"name": "web-research", "description": "look things up"})
    assert isinstance(fm, SkillFrontmatter)
    assert fm.name == "web-research"
    assert fm.description == "look things up"


def test_missing_name_raises() -> None:
    with pytest.raises(SkillParseError):
        validate_frontmatter({"description": "d"})


def test_missing_description_raises() -> None:
    with pytest.raises(SkillParseError):
        validate_frontmatter({"name": "web-research"})


def test_non_string_name_raises() -> None:
    # parser 可能把 name: [a, b] 解析成 list；name 必须是 str。
    with pytest.raises(SkillParseError):
        validate_frontmatter({"name": ["a", "b"], "description": "d"})


@pytest.mark.parametrize("bad", ["WebResearch", "web_research", "-lead", "trail-", "a b"])
def test_invalid_name_pattern_raises(bad: str) -> None:
    with pytest.raises(SkillParseError):
        validate_frontmatter({"name": bad, "description": "d"})


def test_over_long_name_raises() -> None:
    with pytest.raises(SkillParseError):
        validate_frontmatter({"name": "a" * 65, "description": "d"})


def test_optional_fields_default_to_none() -> None:
    fm = validate_frontmatter({"name": "ok", "description": "d"})
    assert fm.version is None
    assert fm.author is None


def test_directory_name_match_ok_and_mismatch_raises() -> None:
    validate_directory_name("web-research", "web-research")  # no raise
    with pytest.raises(ValueError):
        validate_directory_name("other-dir", "web-research")
