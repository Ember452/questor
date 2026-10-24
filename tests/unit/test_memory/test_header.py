"""Mirror test for ``capabilities/memory/header.py`` (plan 01, R7).

Scope note: parsing and scanning are exercised by the memory tests that read real
files. This file covers the value object itself, which had no test: which fields are
required, what the defaults mean for a caller, and that a header cannot be mutated or
share a default container between instances.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from questorharness.capabilities.memory.header import MemoryHeader

_REQUIRED = {
    "path": Path("/tmp/mem/note.md"),
    "title": "Note",
    "description": "What the note says",
    "modified_at": 1_700_000_000.0,
}


def _header(**overrides) -> MemoryHeader:
    return MemoryHeader(**{**_REQUIRED, **overrides})


def test_a_minimal_header_carries_the_four_required_fields() -> None:
    header = _header()

    assert header.path == Path("/tmp/mem/note.md")
    assert header.title == "Note"
    assert header.description == "What the note says"
    assert header.modified_at == 1_700_000_000.0


def test_required_fields_cannot_be_dropped() -> None:
    for missing in ("path", "title", "description", "modified_at"):
        kwargs = {key: value for key, value in _REQUIRED.items() if key != missing}
        with pytest.raises(TypeError):
            MemoryHeader(**kwargs)


def test_optional_fields_default_to_the_empty_side() -> None:
    header = _header()

    assert header.memory_type == ""
    assert header.body_preview == ""
    assert header.id == ""
    assert header.schema_version == 0
    assert header.category == ""
    assert header.importance == 0
    assert header.source == ""
    assert header.signature == ""
    assert header.created_at == ""
    assert header.updated_at == ""
    assert header.relative_path == ""
    assert header.supersedes == ()
    assert header.tags == ()
    assert header.frontmatter == {}


def test_missing_ttl_and_enabled_state_are_explicit_defaults() -> None:
    header = _header()

    assert header.ttl_days is None
    assert header.disabled is False


def test_header_is_immutable() -> None:
    header = _header()

    with pytest.raises(FrozenInstanceError):
        header.title = "Renamed"  # type: ignore[misc]


def test_default_containers_are_not_shared_between_instances() -> None:
    first = _header()
    second = _header()

    first.frontmatter["k"] = "v"
    assert second.frontmatter == {}
    assert first.tags == second.tags == ()


def test_two_headers_with_the_same_fields_compare_equal() -> None:
    header = _header(tags=("a", "b"), ttl_days=7, disabled=True, supersedes=("old.md",))
    twin = _header(tags=("a", "b"), ttl_days=7, disabled=True, supersedes=("old.md",))

    assert header == twin
    assert header.tags == ("a", "b")
    assert header.supersedes == ("old.md",)
    assert header.ttl_days == 7
    assert header.disabled is True


def test_a_header_cannot_be_hashed_because_it_carries_a_dict() -> None:
    # ``frozen=True`` asks dataclasses to generate ``__hash__``, but the frontmatter field
    # is a dict, so hashing raises TypeError. Headers are compared by value and passed as
    # records; they cannot be set members or dict keys. Pinned here so a caller learns it
    # from this file instead of from a crash in production.
    header = _header()

    with pytest.raises(TypeError):
        hash(header)

    with pytest.raises(TypeError):
        _ = {header}
