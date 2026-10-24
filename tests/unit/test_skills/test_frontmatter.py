"""Mirror test for ``skills/frontmatter.py`` (plan 01, R7).

Scope note: the module was called ``_frontmatter`` while four of its functions are public
and two other modules import it, so the underscore described a privacy it never had (and
forced a double-underscore test name). No test named these functions before this file.
Skill metadata decides whether a skill is discoverable and how it is described to the
model, and the parser has to survive hand-written SKILL.md files -- so the fallback
ladder and the permissive boolean spellings are the contract worth pinning.
"""

from __future__ import annotations

import pytest

from questorharness.capabilities.skills.frontmatter import (
    optional_frontmatter_str,
    parse_bool_frontmatter,
    parse_skill_frontmatter,
    parse_skill_metadata,
)

# --- permissive booleans --------------------------------------------------


@pytest.mark.parametrize("value", [True, "true", "TRUE", " yes ", "on", "1", 1])
def test_truthy_spellings_all_mean_true(value: object) -> None:
    assert parse_bool_frontmatter(value, default=False) is True


@pytest.mark.parametrize("value", [False, "false", "No", " off ", "0"])
def test_falsy_spellings_all_mean_false(value: object) -> None:
    assert parse_bool_frontmatter(value, default=True) is False


def test_an_absent_value_uses_the_declared_default() -> None:
    assert parse_bool_frontmatter(None, default=True) is True
    assert parse_bool_frontmatter(None, default=False) is False


@pytest.mark.parametrize("value", ["maybe", "", "   ", "2", [], {}, "yep"])
def test_an_unrecognised_value_never_flips_the_default(value: object) -> None:
    assert parse_bool_frontmatter(value, default=True) is True
    assert parse_bool_frontmatter(value, default=False) is False


# --- optional strings -----------------------------------------------------


def test_a_string_is_stripped_and_a_missing_one_is_none() -> None:
    assert optional_frontmatter_str("  pinned  ") == "pinned"
    assert optional_frontmatter_str("") is None
    assert optional_frontmatter_str("   ") is None


@pytest.mark.parametrize("value", [None, 5, True, ["a"], {"k": "v"}])
def test_only_strings_count_as_provided_values(value: object) -> None:
    assert optional_frontmatter_str(value) is None


# --- skill metadata -------------------------------------------------------


def test_frontmatter_wins_over_the_body_and_is_returned_for_callers_to_read() -> None:
    content = "---\nname: release\ndescription: Ship a release\n---\n# Heading\nbody line\n"

    metadata = parse_skill_metadata("dir-name", content)

    assert metadata["name"] == "release"
    assert metadata["description"] == "Ship a release"
    assert metadata["frontmatter"] == {"name": "release", "description": "Ship a release"}


def test_a_folded_block_scalar_is_parsed_as_one_description() -> None:
    content = "---\nname: review\ndescription: >\n  one line\n  two line\n---\nbody\n"

    metadata = parse_skill_metadata("review-dir", content)

    assert metadata["description"] == "one line two line"


def test_a_quoted_value_keeps_its_inner_punctuation() -> None:
    content = '---\nname: q\ndescription: "handles: colons"\n---\n'

    assert parse_skill_metadata("q", content)["description"] == "handles: colons"


def test_a_non_mapping_frontmatter_keeps_the_default_name_and_leaks_a_metadata_line() -> None:
    """Pinned, not blessed: the body scan starts at line 0.

    The fallback scan only skips lines starting with ``---`` or ``#``, so when the
    fenced block is not a mapping its own keys are read as prose. Ledger row 113 records
    the fix (skip the block once it has been recognised); until then this is the contract.
    """
    metadata = parse_skill_metadata("fall", "---\n- just\n- a\n- list\n---\n# Real name\nreal body\n")

    assert metadata["frontmatter"] == {}
    assert metadata["name"] == "fall"
    assert metadata["description"] == "- just"


def test_broken_yaml_leads_its_own_key_line_as_the_description() -> None:
    content = "---\nname: [unclosed\ndescription: }\n---\n# Fallback Title\nfirst paragraph\n"

    metadata = parse_skill_metadata("dir-name", content)

    assert metadata["frontmatter"] == {}
    assert metadata["name"] == "dir-name"
    assert metadata["description"] == "name: [unclosed"


def test_an_unclosed_frontmatter_block_is_read_as_body_text() -> None:
    content = "---\nname: never-closed\ndescription: invisible\n"

    metadata = parse_skill_metadata("dir-name", content)

    assert metadata["name"] == "dir-name"
    assert metadata["description"] == "name: never-closed"
    assert metadata["frontmatter"] == {}


def test_a_skill_with_a_description_only_in_the_body_still_gets_both() -> None:
    metadata = parse_skill_metadata("dir", "# Title\n\nUse this when releasing.\n")

    assert metadata["name"] == "Title"
    assert metadata["description"] == "Use this when releasing."


def test_a_long_first_paragraph_is_cut_at_two_hundred_characters() -> None:
    metadata = parse_skill_metadata("dir", "# T\n" + "word " * 100)

    assert len(metadata["description"]) == 200


def test_the_default_name_is_used_when_no_heading_is_present() -> None:
    metadata = parse_skill_metadata("bare", "just a body line, no heading")

    assert metadata["name"] == "bare"
    assert metadata["description"] == "just a body line, no heading"


def test_the_fallback_template_can_be_reworded_by_the_caller() -> None:
    # Only a heading and no prose: this is the one shape that reaches the template.
    metadata = parse_skill_metadata("cmd", "# Release tool\n", fallback_template="Run {name}")

    assert metadata["name"] == "Release tool"
    assert metadata["description"] == "Run Release tool"


def test_an_empty_file_still_produces_a_usable_pair() -> None:
    metadata = parse_skill_metadata("empty", "")

    assert metadata == {"name": "empty", "description": "Skill: empty", "frontmatter": {}}


def test_the_tuple_view_agrees_with_the_metadata_dict() -> None:
    content = "---\nname: twin\ndescription: same\ndisable-model-invocation: true\n---\n"

    name, description = parse_skill_frontmatter("dir", content)
    metadata = parse_skill_metadata("dir", content)

    assert (name, description) == (metadata["name"], metadata["description"])


def test_the_tuple_view_reports_only_name_and_description() -> None:
    assert parse_skill_frontmatter("dir", "") == ("dir", "Skill: dir")
