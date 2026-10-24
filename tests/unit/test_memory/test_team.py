"""Mirror test for ``capabilities/memory/team.py`` (plan 01, R7).

Scope note: nothing under ``tests/`` named ``SecretMatch``, ``scan_for_secrets`` or
``get_team_memory_dir`` before this file. This module is the last check between a
project memory entry and a **shared** vault that collaborators read, and it is also
the guard that decides whether a write path escapes the vault -- so both the pattern
rules and the traversal refusals are pinned here, including the near-misses that must
NOT trip (an over-eager secret rule silently deletes useful memory).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.memory.paths import get_project_memory_dir
from questorharness.capabilities.memory.team import (
    MEMORY_INDEX,
    TEAM_DIR_NAME,
    SecretMatch,
    check_team_memory_secrets,
    ensure_team_memory_vault,
    get_team_memory_dir,
    scan_for_secrets,
    validate_team_memory_write_path,
)

SECRET_SAMPLES = {
    "private-key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...",
    "aws-access-key": "key AKIAIOSFODNN7EXAMPLE here",
    "github-token": "ghp_" + "A" * 36,
    "openai-key": "sk-" + "aB3dE5fG" * 3,
    "anthropic-key": "sk-ant-" + "aB3dE5fG" * 3,
    "generic-secret": 'password = "correcthorsebattery"',
}


@pytest.fixture()
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "repo"
    root.mkdir()
    return root


def rule_ids(content: str) -> set[str]:
    return {match.rule_id for match in scan_for_secrets(content)}


# --- the vault location ---------------------------------------------------


def test_the_team_vault_lives_inside_the_project_memory_dir(project: Path) -> None:
    team_dir = get_team_memory_dir(project)

    assert team_dir.name == TEAM_DIR_NAME == "team"
    assert team_dir == get_project_memory_dir(project) / "team"


def test_ensuring_the_vault_creates_the_index_once_and_never_twice(project: Path) -> None:
    first = ensure_team_memory_vault(project)

    assert first.is_dir()
    assert (first / MEMORY_INDEX).read_text(encoding="utf-8") == "# Memory Index\n"

    (first / MEMORY_INDEX).write_text("# Memory Index\n- [kept](a.md)\n", encoding="utf-8")
    ensure_team_memory_vault(project)

    # Re-ensuring must not clobber an index the user has since written to.
    assert "- [kept](a.md)" in (first / MEMORY_INDEX).read_text(encoding="utf-8")


# --- secret detection -----------------------------------------------------


@pytest.mark.parametrize("rule_id", sorted(SECRET_SAMPLES))
def test_each_rule_catches_its_own_shape(rule_id: str) -> None:
    assert rule_id in rule_ids(SECRET_SAMPLES[rule_id])


def test_ordinary_memory_text_is_not_flagged() -> None:
    content = (
        "The gateway restarts the sandbox when the port changes.\n"
        "Ask the user for the token they use in demos; never store it.\n"
        "Placeholder: sk-abc123 (a doc example, far below the real key length)"
    )

    assert scan_for_secrets(content) == []
    assert check_team_memory_secrets(content) is None


@pytest.mark.parametrize(
    "content",
    [
        "AKIA1234567890",  # aws keys are 16 chars after the prefix
        "sk-ant-abc",  # too short to be a real anthropic key
        "ghp_short",  # too short to be a real github token
        "password: tiny",  # assignment below the 12 character body
        "token",  # a bare word is not an assignment
    ],
)
def test_near_misses_stay_allowed(content: str) -> None:
    assert scan_for_secrets(content) == []


def test_the_generic_rule_is_spelling_and_case_insensitive() -> None:
    for content in (
        'API_KEY="abcdefghijklmnop"',
        "api-key: abcdefghijklmnop",
        "secret = 'abcdefghijklmnop'",
        "Authorization Token=abcdefghijklmnop",
    ):
        assert "generic-secret" in rule_ids(content), content


def test_a_match_never_carries_the_secret_itself() -> None:
    matches = scan_for_secrets(SECRET_SAMPLES["openai-key"])

    assert matches
    assert all(isinstance(match, SecretMatch) for match in matches)
    assert all(match.rule_id and match.label for match in matches)
    # The whole point: the report can be logged or shown without leaking the value.
    leaked = SECRET_SAMPLES["openai-key"].split("-", 1)[1]
    assert all(leaked not in repr(match) for match in matches)


def test_several_problems_are_listed_together_in_rule_order() -> None:
    content = SECRET_SAMPLES["github-token"] + "\n" + SECRET_SAMPLES["aws-access-key"]

    message = check_team_memory_secrets(content)

    assert message is not None
    # Labels come out in SECRET_RULES order, which keeps the report stable.
    assert "AWS access key, GitHub token" in message
    assert "shared with project collaborators" in message
    # The refusal never echoes the secret back.
    assert SECRET_SAMPLES["github-token"] not in message


# --- write-path validation -----------------------------------------------


def test_validating_a_path_creates_the_vault_as_a_side_effect(project: Path) -> None:
    """Pinned, not blessed: the validator calls ``ensure_team_memory_vault`` internally.

    Asking "may I write here?" therefore creates directories. Recorded in ledger row 111
    as something to change on a memory-semantics knife, and asserted here so the change
    is a deliberate edit instead of an accident.
    """
    team_dir = get_team_memory_dir(project)
    assert not team_dir.exists()

    resolved, error = validate_team_memory_write_path(project, "noted.md")

    assert error is None and resolved is not None
    assert team_dir.is_dir()
    assert (team_dir / MEMORY_INDEX).exists()


def test_relative_targets_land_inside_the_vault(project: Path) -> None:
    team_dir = ensure_team_memory_vault(project)

    resolved, error = validate_team_memory_write_path(project, "notes/insight.md")

    assert error is None
    assert resolved == (team_dir / "notes" / "insight.md").resolve()


def test_absolute_targets_inside_the_vault_are_accepted(project: Path) -> None:
    team_dir = ensure_team_memory_vault(project)

    resolved, error = validate_team_memory_write_path(project, team_dir / "a.md")

    assert error is None
    assert resolved is not None and resolved.name == "a.md"


@pytest.mark.parametrize("candidate", ["../escape.md", "notes/../../escape.md", "./../escape.md"])
def test_relative_traversal_is_refused(project: Path, candidate: str) -> None:
    resolved, error = validate_team_memory_write_path(project, candidate)

    assert resolved is None
    assert error is not None and "escapes team memory directory" in error


def test_an_absolute_target_outside_the_vault_is_refused(project: Path) -> None:
    team_dir = ensure_team_memory_vault(project)
    outside = project.parent / "somewhere-else.md"

    resolved, error = validate_team_memory_write_path(project, outside)

    assert resolved is None
    assert error is not None
    assert str(team_dir) in error or "escapes" in error


def test_a_missing_nested_target_is_still_allowed_since_it_cannot_escape(project: Path) -> None:
    team_dir = ensure_team_memory_vault(project)

    resolved, error = validate_team_memory_write_path(project, "deep/deeper/file.md")

    assert error is None
    assert resolved == (team_dir / "deep" / "deeper" / "file.md").resolve()


def test_a_written_file_can_be_moved_out_only_through_the_vault(project: Path) -> None:
    team_dir = ensure_team_memory_vault(project)
    outside = project / "outside"
    outside.mkdir()
    link = team_dir / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this host")
    if not link.is_symlink():  # pragma: no cover - windows fallback
        pytest.skip("symlink creation reported success but produced no link")

    resolved, error = validate_team_memory_write_path(project, "link/secret.md")

    assert resolved is None
    assert error is not None and "via symlink" in error
