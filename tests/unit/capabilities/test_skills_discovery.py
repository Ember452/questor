"""SKILL.md 发现 + 单文件失败隔离的判红用例（C05，TDD）。

真源：`docs/plan/05` DoD①/T8；改造 crewAI `skills/loader.py:44-117`（逐目录 try/except→告警→继续）。
用 **tmp_path 真文件 + caplog** 断言（不用 mock 冒充 IO）。坏文件必须"出声且被跳过"、
其余技能照常发现（C6：连接/解析失败绝不静默）。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from questor.capabilities.skills.loader import discover_skills
from questor.capabilities.skills.models import DisclosureLevel


def _write_skill(root: Path, name: str, content: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def test_discovers_valid_skill_at_metadata_level(tmp_path: Path) -> None:
    _write_skill(tmp_path, "web-research", "---\nname: web-research\ndescription: look up\n---\n# body")
    skills = discover_skills(tmp_path)
    assert [s.frontmatter.name for s in skills] == ["web-research"]
    assert skills[0].disclosure_level is DisclosureLevel.METADATA
    assert skills[0].body is None  # METADATA 不读正文（渐进披露）


def test_broken_skill_is_skipped_and_warned_good_ones_still_found(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_skill(tmp_path, "good", "---\nname: good\ndescription: d\n---\nb")
    _write_skill(tmp_path, "broken", "name: broken\nno delimiters at all")  # 缺 --- → 解析失败
    with caplog.at_level(logging.WARNING, logger="questor.skills"):
        skills = discover_skills(tmp_path)
    assert [s.frontmatter.name for s in skills] == ["good"]  # 坏文件不拖垮发现
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.skills"]
    assert any("broken" in m for m in warns)  # 但一定出声（C6）


def test_directory_name_mismatch_is_skipped_and_warned(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_skill(tmp_path, "dir-name", "---\nname: other\ndescription: d\n---\nb")  # 声明名 != 目录名
    with caplog.at_level(logging.WARNING, logger="questor.skills"):
        skills = discover_skills(tmp_path)
    assert skills == []
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.skills"]
    assert any("other" in m or "dir-name" in m for m in warns)


def test_dir_without_skill_md_is_ignored_silently(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "not-a-skill").mkdir()  # 无 SKILL.md，是普通目录，非坏技能 → 静默跳过
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")  # 顶层文件 → 忽略
    with caplog.at_level(logging.WARNING, logger="questor.skills"):
        skills = discover_skills(tmp_path)
    assert skills == []
    assert [r for r in caplog.records if r.name == "questor.skills"] == []  # 不是技能尝试失败，不该告警


def test_missing_search_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_skills(tmp_path / "nope")
