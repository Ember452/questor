"""Mirror test for ``capabilities/memory/entry_store.py`` (plan 01, R7).

Scope note: the frontmatter schema and the content-signature dedupe are already
covered by ``tests/unit/test_memory/test_memdir.py``. This file pins the parts of
the store that had no test at all: the lock location, slug collision numbering, the
listing order, and what a soft delete does to both the file and the ``MEMORY.md``
index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.memory.entry_store import (
    _memory_lock_path,
    _next_memory_path,
    add_memory_entry,
    list_memory_files,
    remove_memory_entry,
)
from questorharness.capabilities.memory.paths import get_memory_entrypoint, get_project_memory_dir


@pytest.fixture()
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("QUESTOR_WORKSPACE", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_lock_lives_inside_the_project_memory_dir(project: Path) -> None:
    lock = _memory_lock_path(project)

    assert lock.name == ".memory.lock"
    assert lock.parent == get_project_memory_dir(project)


def test_next_memory_path_increments_until_free(tmp_path: Path) -> None:
    assert _next_memory_path(tmp_path, "notes") == tmp_path / "notes.md"

    (tmp_path / "notes.md").write_text("taken\n", encoding="utf-8")
    assert _next_memory_path(tmp_path, "notes") == tmp_path / "notes_2.md"

    (tmp_path / "notes_2.md").write_text("taken\n", encoding="utf-8")
    assert _next_memory_path(tmp_path, "notes") == tmp_path / "notes_3.md"


def test_title_becomes_a_slug_and_collisions_get_a_suffix(project: Path) -> None:
    first = add_memory_entry(project, "Pytest Tips!", "Prefer fixtures over setup.")
    second = add_memory_entry(project, "Pytest Tips!", "Different body, same slug.")

    assert first.name == "pytest_tips.md"
    assert second.name == "pytest_tips_2.md"
    assert list_memory_files(project) == sorted([first, second])


def test_unmappable_title_falls_back_to_a_generic_slug(project: Path) -> None:
    path = add_memory_entry(project, "!!! ???", "Nothing a slug could be built from.")

    assert path.parent == get_project_memory_dir(project)
    assert path.name == "memory.md"


def test_index_lists_each_own_file_once(project: Path) -> None:
    path = add_memory_entry(project, "Indexed", "First body.")
    add_memory_entry(project, "Indexed", "Second body forces a new file.")

    index = get_memory_entrypoint(project).read_text(encoding="utf-8")

    assert index.count(path.name) == 1
    assert f"- [Indexed]({path.name})" in index


def test_list_memory_files_is_sorted_and_scoped_to_the_project(project: Path) -> None:
    added = [add_memory_entry(project, f"Note {n}", f"Body {n}.") for n in (3, 1, 2)]

    listed = list_memory_files(project)

    assert listed == sorted(added)
    assert all(path.parent == get_project_memory_dir(project) for path in listed)


def test_removing_an_unknown_entry_reports_false(project: Path) -> None:
    add_memory_entry(project, "Kept", "Still relevant.")

    assert remove_memory_entry(project, "no-such-note") is False
    assert len(list_memory_files(project)) == 1


def test_remove_soft_deletes_the_file_and_unindexes_it(project: Path) -> None:
    path = add_memory_entry(project, "Retire me", "Body that should stop being recalled.")

    assert remove_memory_entry(project, "retire_me") is True
    assert path.exists()
    assert path not in list_memory_files(project)
    assert path.name not in get_memory_entrypoint(project).read_text(encoding="utf-8")

    # A second delete has nothing left to do: the entry is already disabled.
    assert remove_memory_entry(project, "retire_me") is False


def test_remove_also_accepts_the_title_or_file_name(project: Path) -> None:
    add_memory_entry(project, "Alias lookup", "Findable by title, stem or file name.")

    assert remove_memory_entry(project, "Alias lookup") is True
    assert remove_memory_entry(project, "alias_lookup.md") is False
