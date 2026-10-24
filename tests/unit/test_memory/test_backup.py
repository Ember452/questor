"""Mirror test for ``memory/consolidate/backup.py`` (plan 01, R7).

Scope note: no test named any of these six functions before this file, and one of them
(``restore_memory_backup``) deletes the live memory directory as its second step. A wrong
assumption here is data loss, so the interesting questions are exactly which files are
kept out of a backup, what happens to a name collision inside the same second, and
whether "restore" merges or replaces.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from questorharness.capabilities.memory.consolidate.backup import (
    create_memory_backup,
    default_backup_root,
    diff_memory_dirs,
    format_memory_diff,
    latest_memory_backup,
    restore_memory_backup,
)


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path) -> None:
    """Never let a backup test write into the real user data directory."""
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture()
def memory_dir(tmp_path) -> Path:
    directory = tmp_path / "memory"
    directory.mkdir()
    (directory / "a.md").write_text("first\n", encoding="utf-8")
    (directory / "b.md").write_text("second\n", encoding="utf-8")
    return directory


# --- where backups go ----------------------------------------------------


def test_a_project_local_questor_directory_keeps_its_backups_next_to_it(tmp_path) -> None:
    project = tmp_path / ".questor" / "memory"
    project.mkdir(parents=True)

    assert default_backup_root(project) == (tmp_path / ".questor" / "backups").resolve()


def test_any_other_memory_dir_falls_back_to_the_app_data_directory(memory_dir, tmp_path) -> None:
    assert default_backup_root(memory_dir) == (tmp_path / "data" / "memory-backups" / "questorharness").resolve()


def test_an_application_label_is_made_safe_for_a_directory_name(memory_dir, tmp_path) -> None:
    root = default_backup_root(memory_dir, app_label="my app/../v2")

    # One dash per unsafe character: the separators are not collapsed.
    assert root.name == "my-app----v2", root.name
    assert ".." not in root.parts
    assert root.parent == (tmp_path / "data" / "memory-backups").resolve()


def test_an_empty_label_falls_back_to_the_default_product_name(memory_dir) -> None:
    assert default_backup_root(memory_dir, app_label="///").name == "questorharness"


# --- making a backup -----------------------------------------------------


def test_a_backup_copies_the_memory_files_but_not_the_lock(memory_dir) -> None:
    (memory_dir / ".consolidate-lock").write_text("held", encoding="utf-8")
    (memory_dir / "sub").mkdir()
    (memory_dir / "sub" / "nested.md").write_text("nested\n", encoding="utf-8")

    backup = create_memory_backup(memory_dir, backup_root=memory_dir.parent / "backups")

    assert backup.name.startswith("memory-")
    assert (backup / "a.md").read_text(encoding="utf-8") == "first\n"
    assert (backup / "sub" / "nested.md").exists()
    assert not (backup / ".consolidate-lock").exists()


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(memory_dir) -> None:
    root = memory_dir.parent / "backups"
    first = create_memory_backup(memory_dir, backup_root=root)

    # Force the collision by pre-creating the name the second call would choose.
    stamp = time.strftime("memory-%Y%m%d-%H%M%S")
    (root / f"{stamp}-2").mkdir()

    second = create_memory_backup(memory_dir, backup_root=root)

    assert second != first
    assert second.name == f"{stamp}-3"


def test_backing_up_a_memory_dir_that_does_not_exist_yet_makes_an_empty_backup(tmp_path) -> None:
    missing = tmp_path / "nothing-here"

    backup = create_memory_backup(missing, backup_root=tmp_path / "backups")

    assert backup.is_dir()
    assert list(backup.iterdir()) == []


# --- diffing -------------------------------------------------------------


def test_a_diff_reports_added_removed_and_changed_in_that_key_order(memory_dir, tmp_path) -> None:
    later = tmp_path / "after"
    later.mkdir()
    (later / "a.md").write_text("first edited\n", encoding="utf-8")
    (later / "c.md").write_text("new\n", encoding="utf-8")

    diff = diff_memory_dirs(memory_dir, later)

    assert diff == {"added": ["c.md"], "removed": ["b.md"], "changed": ["a.md"]}


def test_identical_content_is_not_reported_as_changed(memory_dir, tmp_path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    for name in ("a.md", "b.md"):
        (copy / name).write_text((memory_dir / name).read_text(encoding="utf-8"), encoding="utf-8")

    assert diff_memory_dirs(memory_dir, copy) == {"added": [], "removed": [], "changed": []}


def test_only_markdown_files_are_compared(memory_dir, tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (memory_dir / "notes.txt").write_text("plain\n", encoding="utf-8")

    diff = diff_memory_dirs(memory_dir, other)

    assert "notes.txt" not in diff["removed"]
    assert diff["removed"] == ["a.md", "b.md"]


def test_a_missing_side_makes_everything_one_sided(tmp_path, memory_dir) -> None:
    missing = tmp_path / "gone"

    assert diff_memory_dirs(missing, memory_dir) == {"added": ["a.md", "b.md"], "removed": [], "changed": []}
    assert diff_memory_dirs(memory_dir, missing) == {"added": [], "removed": ["a.md", "b.md"], "changed": []}


def test_the_formatting_order_is_added_changed_removed() -> None:
    rendered = format_memory_diff({"added": ["c.md"], "removed": ["a.md"], "changed": ["b.md", "z.md"]})

    assert rendered == "added: c.md\nchanged: b.md, z.md\nremoved: a.md"


def test_an_empty_or_partial_diff_says_so() -> None:
    assert format_memory_diff({"added": [], "removed": [], "changed": []}) == "no markdown file changes"
    assert format_memory_diff({}) == "no markdown file changes"
    assert format_memory_diff({"changed": ["a.md"]}) == "changed: a.md"


# --- finding and applying the latest backup ------------------------------


def test_no_backup_exists_yet(tmp_path) -> None:
    assert latest_memory_backup(tmp_path / "memory") is None


def test_only_directories_named_as_backups_are_candidates(memory_dir) -> None:
    root = default_backup_root(memory_dir)
    root.mkdir(parents=True)
    (root / "not-a-backup").mkdir()
    (root / "memory-stray.txt").write_text("x", encoding="utf-8")

    assert latest_memory_backup(memory_dir) is None


def test_the_newest_backup_by_mtime_wins(memory_dir) -> None:
    root = default_backup_root(memory_dir)
    older = create_memory_backup(memory_dir, backup_root=root)
    newest = create_memory_backup(memory_dir, backup_root=root)
    stamp = time.time()
    os.utime(older, (stamp - 500, stamp - 500))
    os.utime(newest, (stamp, stamp))

    assert latest_memory_backup(memory_dir) == newest


def test_restoring_replaces_the_live_directory_rather_than_merging_it(memory_dir) -> None:
    root = memory_dir.parent / "backups"
    backup = create_memory_backup(memory_dir, backup_root=root)
    (memory_dir / "b.md").unlink()
    (memory_dir / "written-since.md").write_text("created after the backup\n", encoding="utf-8")

    restore_memory_backup(backup, memory_dir)

    assert sorted(path.name for path in memory_dir.glob("*.md")) == ["a.md", "b.md"]
    assert not (memory_dir / "written-since.md").exists()
    assert not (memory_dir.parent / f".{memory_dir.name}.restore-tmp").exists()


def test_restoring_from_a_missing_or_non_directory_backup_refuses(tmp_path, memory_dir) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    for candidate in (tmp_path / "nope", not_a_dir):
        with pytest.raises(FileNotFoundError, match="Backup not found"):
            restore_memory_backup(candidate, memory_dir)

    # The live directory is untouched by a refused restore.
    assert (memory_dir / "a.md").exists()


def test_restoring_into_a_fresh_location_works_without_replacing_anything(memory_dir, tmp_path) -> None:
    backup = create_memory_backup(memory_dir, backup_root=tmp_path / "backups")
    target = tmp_path / "restored"

    restore_memory_backup(backup, target)

    assert sorted(path.name for path in target.glob("*.md")) == ["a.md", "b.md"]
