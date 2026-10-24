"""Mirror test for ``capabilities/memory/relevance.py`` (plan 01, R7).

Scope note: ``RelevantMemory``, ``build_memory_manifest``, ``select_manifest_memories``
and ``json_selector_from_text`` were named in no test before this file. This module
decides **which memories reach the model** and what order the model sees them in, so
the selector contract (unknown paths dropped, duplicates collapsed, backfill when the
reranker returns too little, hard cap at ``max_results``) is pinned rather than left to
chance -- those are the four ways a reranker can silently degrade context quality.
"""

from __future__ import annotations

import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from questorharness.capabilities.memory.entry_store import add_memory_entry
from questorharness.capabilities.memory.header import MemoryHeader
from questorharness.capabilities.memory.relevance import (
    RelevantMemory,
    build_memory_manifest,
    format_relevant_memories,
    json_selector_from_text,
    select_manifest_memories,
    select_relevant_memories,
)

DAY = 86400.0


def header(name: str, **kwargs) -> MemoryHeader:
    base = {
        "path": Path("/mem") / name,
        "title": name,
        "description": "",
        "modified_at": time.time(),
        "relative_path": name,
    }
    return MemoryHeader(**(base | kwargs))


@pytest.fixture()
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("QUESTOR_WORKSPACE", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    return root


# --- the manifest ---------------------------------------------------------


def test_an_empty_manifest_is_an_empty_string() -> None:
    assert build_memory_manifest([]) == ""


def test_a_manifest_line_is_type_path_age_then_description() -> None:
    now = time.time()

    manifest = build_memory_manifest(
        [
            header("docker.md", description="Compose caveats", memory_type="project"),
            header("stale.md", description="Old note", modified_at=now - 2 * DAY),
        ]
    )

    lines = manifest.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[project] docker.md")
    assert lines[0].endswith("(today) - Compose caveats")
    # A memory without a declared type is still listed, under the generic label.
    assert lines[1].startswith("[memory] stale.md (2 days ago) - Old note")


def test_a_header_without_a_description_omits_the_dash() -> None:
    line = build_memory_manifest([header("bare.md")])

    assert line == "[memory] bare.md (today)"


def test_a_manifest_falls_back_to_the_file_name_when_relative_path_is_missing() -> None:
    line = build_memory_manifest([header("deep.md", relative_path="")])

    assert " deep.md " in f" {line} "


# --- selector response parsing -------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('["a.md", "b.md"]', ["a.md", "b.md"]),
        ('{"paths": ["a.md", "b.md"]}', ["a.md", "b.md"]),
        ("a.md\nb.md", ["a.md", "b.md"]),
        ("- a.md\n- b.md", ["a.md", "b.md"]),
        ("", []),
        ("   \n  ", []),
        ("[]", []),
        ('{"paths": []}', []),
        ('{"note": "no list here"}', []),
        ("null", []),
        ("5", []),
        ('["a.md", "", "  ", "b.md"]', ["a.md", "b.md"]),
        ('["a.md", 7]', ["a.md", "7"]),
    ],
)
def test_a_selector_answer_is_parsed_whichever_shape_the_model_returns(text: str, expected: list[str]) -> None:
    assert json_selector_from_text(text) == expected


# --- selection contract ---------------------------------------------------


def test_the_selector_order_wins_and_unknown_paths_are_dropped(project: Path) -> None:
    for name in ("alpha", "beta", "gamma"):
        add_memory_entry(project, name, f"notes about {name}")

    def selector(query: str, headers: list[MemoryHeader]) -> list[str]:
        assert query == "notes"
        return ["gamma.md", "missing.md", "alpha.md", "alpha.md"]

    chosen = select_manifest_memories("notes", project, max_results=5, selector=selector)

    # Requested order first, unknown path skipped, the duplicate collapsed, and the
    # leftover backfilled so the caller still gets everything it was offered.
    assert [item.header.relative_path for item in chosen] == ["gamma.md", "alpha.md", "beta.md"]


def test_selection_is_capped_at_max_results(project: Path) -> None:
    for index in range(5):
        add_memory_entry(project, f"note{index}", f"shared word {index}")

    chosen = select_manifest_memories("shared", project, max_results=2)

    assert len(chosen) == 2


def test_no_selector_means_the_manifest_order_is_kept(project: Path) -> None:
    add_memory_entry(project, "one", "body one")
    add_memory_entry(project, "two", "body two")

    chosen = select_manifest_memories("body", project, max_results=5)

    assert {item.header.relative_path for item in chosen} == {"one.md", "two.md"}


def test_a_manifest_selection_without_files_returns_nothing(project: Path) -> None:
    assert select_manifest_memories("anything", project, max_results=5) == []


def test_heuristic_selection_skips_what_was_already_surfaced(project: Path) -> None:
    add_memory_entry(project, "pytest", "pytest fixtures and markers")
    add_memory_entry(project, "docker", "docker compose networking")

    fresh = select_relevant_memories("pytest fixtures", project, max_results=5)
    assert {item.header.relative_path for item in fresh} == {"pytest.md"}

    surfaced = select_relevant_memories("pytest fixtures", project, max_results=5, already_surfaced={"pytest.md"})
    assert surfaced == []

    other = select_relevant_memories("docker compose", project, max_results=5, already_surfaced={"pytest.md"})
    assert {item.header.relative_path for item in other} == {"docker.md"}


def test_a_fresh_memory_carries_no_staleness_warning_but_an_old_one_does(project: Path) -> None:
    add_memory_entry(project, "fresh", "brand new fact")

    fresh = select_relevant_memories("brand new fact", project, max_results=5)
    assert fresh and fresh[0].freshness == ""

    stale_path = next(iter(select_relevant_memories("brand new fact", project, max_results=5))).header.path
    old = time.time() - 30 * DAY
    os.utime(stale_path, (old, old))

    stale = select_relevant_memories("brand new fact", project, max_results=5)
    assert stale[0].freshness.startswith("This memory is 30 days old")
    assert "verify claims" in stale[0].freshness


# --- rendering -----------------------------------------------------------


def test_formatting_wraps_each_memory_in_a_fenced_block(tmp_path: Path) -> None:
    stored = tmp_path / "fmt.md"
    stored.write_text("use fixtures over setup\n", encoding="utf-8")

    rendered = format_relevant_memories(
        [RelevantMemory(header=header("fmt.md", path=stored), freshness="")],
    )

    assert rendered.startswith("# Relevant Memories\n")
    assert "## fmt.md" in rendered
    assert "```md" in rendered
    assert "use fixtures over setup" in rendered
    # No freshness line at all when the memory is new.
    assert "> " not in rendered
    assert stored.exists()


def test_formatting_shows_the_staleness_line_above_the_body(tmp_path: Path) -> None:
    stored = tmp_path / "old.md"
    stored.write_text("ancient truth", encoding="utf-8")

    rendered = format_relevant_memories(
        [RelevantMemory(header=header("old.md", path=stored), freshness="28 days old")]
    )

    lines = rendered.splitlines()
    assert lines[0] == "# Relevant Memories"
    assert lines[1] == ""
    assert lines[2] == "## old.md"
    assert lines[3] == "> 28 days old"
    assert lines[4] == "```md"


def test_formatting_truncates_a_long_body(tmp_path: Path) -> None:
    stored = tmp_path / "big.md"
    stored.write_text("x" * 400, encoding="utf-8")

    rendered = format_relevant_memories(
        [RelevantMemory(header=header("big.md", path=stored))],
        max_chars=50,
    )

    body = rendered.split("```md")[1].split("```")[0].strip()
    assert len(body) == 50


def test_formatting_nothing_produces_just_the_heading() -> None:
    assert format_relevant_memories([]) == "# Relevant Memories"


# --- the value object ----------------------------------------------------


def test_a_relevant_memory_is_a_header_plus_its_freshness() -> None:
    item = header("a.md")

    first = RelevantMemory(header=item)
    second = RelevantMemory(header=item, freshness="stale")

    assert first.freshness == ""
    assert first == RelevantMemory(header=item)
    assert first != second
    with pytest.raises(FrozenInstanceError):
        second.freshness = "changed"  # type: ignore[misc]
