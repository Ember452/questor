"""Mirror test for ``capabilities/skills/definition.py`` (plan 01, R7)."""

from __future__ import annotations

import dataclasses

import pytest

from questorharness.capabilities.skills.definition import SkillDefinition


def test_a_skill_needs_only_its_identity_and_body() -> None:
    skill = SkillDefinition(name="pdf", description="work with pdf", content="# body", source="bundled")

    assert (skill.name, skill.description, skill.content, skill.source) == (
        "pdf",
        "work with pdf",
        "# body",
        "bundled",
    )
    # Optional wiring stays unset rather than collapsing to a falsy stand-in.
    assert skill.path is None
    assert skill.command_name is None
    assert skill.aliases == ()
    assert skill.user_invocable is True
    assert skill.disable_model_invocation is False


def test_definition_is_frozen() -> None:
    skill = SkillDefinition(name="pdf", description="d", content="c", source="plugin")

    with pytest.raises(dataclasses.FrozenInstanceError):
        skill.name = "other"  # type: ignore[misc]


def test_two_definitions_do_not_share_the_alias_tuple_default() -> None:
    first = SkillDefinition(name="a", description="d", content="c", source="bundled")
    second = SkillDefinition(name="b", description="d", content="c", source="bundled")

    assert first.aliases == second.aliases == ()
    assert first.aliases is second.aliases, "an immutable default is safe to share"
