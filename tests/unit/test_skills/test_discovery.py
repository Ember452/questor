"""Mirror test for ``capabilities/skills/bundled/discovery.py`` (plan 01, R7).

Covers the facade re-export plus the frontmatter paths the loaders depend on:
explicit values, defaults when a file has no frontmatter, and the missing
content directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.skills import bundled
from questorharness.capabilities.skills.bundled import discovery

FULL_FRONTMATTER = """---
name: Demo Skill
description: A bundled demo
user-invocable: false
disable-model-invocation: true
model: opus
argument-hint: target
---

Body text.
"""

BARE_MARKDOWN = "# Just a heading\n\nNo frontmatter block here.\n"


def test_facade_reexports_the_discovery_function() -> None:
    """The entry point must keep resolving the same object, not a copy."""
    assert bundled.get_bundled_skills is discovery.get_bundled_skills


def test_get_bundled_skills_reads_declared_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "demo.md").write_text(FULL_FRONTMATTER, encoding="utf-8")
    monkeypatch.setattr(discovery, "_CONTENT_DIR", tmp_path)

    skills = discovery.get_bundled_skills()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "Demo Skill"
    assert skill.description == "A bundled demo"
    assert skill.command_name == "demo"
    assert skill.source == "bundled"
    assert skill.user_invocable is False
    assert skill.disable_model_invocation is True
    assert skill.model == "opus"
    assert skill.argument_hint == "target"
    # A declared name that differs from the file stem becomes the display name.
    assert skill.display_name == "Demo Skill"
    assert Path(skill.path).parent == tmp_path
    assert skill.base_dir == str(tmp_path)


def test_defaults_apply_when_a_file_has_no_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bare.md").write_text(BARE_MARKDOWN, encoding="utf-8")
    monkeypatch.setattr(discovery, "_CONTENT_DIR", tmp_path)

    skills = discovery.get_bundled_skills()

    assert len(skills) == 1
    skill = skills[0]
    # parse_skill_metadata falls back to the ``# heading`` plus the first body
    # paragraph when no frontmatter block is present, so the name is the heading
    # and not the file stem; the stem stays available as command_name.
    assert skill.name == "Just a heading"
    assert skill.description == "No frontmatter block here."
    assert skill.command_name == "bare"
    assert skill.user_invocable is True
    assert skill.disable_model_invocation is False
    assert skill.model is None
    assert skill.argument_hint is None
    # A name that differs from the stem is surfaced as the display name.
    assert skill.display_name == "Just a heading"


def test_skills_are_returned_in_file_name_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "zeta.md").write_text(BARE_MARKDOWN, encoding="utf-8")
    (tmp_path / "alpha.md").write_text(BARE_MARKDOWN, encoding="utf-8")
    monkeypatch.setattr(discovery, "_CONTENT_DIR", tmp_path)

    assert [skill.command_name for skill in discovery.get_bundled_skills()] == ["alpha", "zeta"]


def test_missing_content_directory_yields_no_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "_CONTENT_DIR", tmp_path / "absent")
    assert discovery.get_bundled_skills() == []


def test_parse_frontmatter_delegates_to_the_shared_parser() -> None:
    name, description = discovery._parse_frontmatter("stem", FULL_FRONTMATTER)
    assert (name, description) == ("Demo Skill", "A bundled demo")


def test_parse_metadata_ignores_a_non_mapping_frontmatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        discovery,
        "parse_skill_metadata",
        lambda default_name, content, *, fallback_template: {
            "name": default_name,
            "description": "",
            "frontmatter": "not a mapping",
        },
    )
    metadata = discovery._parse_metadata("stem", "content")
    assert metadata["name"] == "stem"
    assert metadata["user_invocable"] is True
    assert metadata["model"] is None
