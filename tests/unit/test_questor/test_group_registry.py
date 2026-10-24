"""Mirror test for ``questor/group_registry.py`` (plan 01, R7).

Scope note: ``normalize_group_name``, ``normalize_cwd``, ``group_record_path`` and
``ManagedGroupRecord`` appeared in no test before this file. The one that matters most
is ``group_record_path``: a chat id arrives from an external platform and is used to
build a filename, so its sanitising is what keeps a hostile id from writing outside the
registry directory.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime
from pathlib import Path

import pytest

from questor.group_registry import (
    ManagedGroupRecord,
    group_record_path,
    load_managed_group_record,
    normalize_cwd,
    normalize_group_name,
    save_managed_group_record,
)
from questor.workspace import get_groups_dir


@pytest.fixture()
def workspace(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "repo"
    root.mkdir()
    return root


# --- names ---------------------------------------------------------------


def test_a_group_name_is_trimmed_and_internally_collapsed() -> None:
    assert normalize_group_name("  release   crew  ") == "release crew"


def test_a_tab_separated_name_becomes_one_space() -> None:
    assert normalize_group_name("a\t\nb") == "a b"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n "])
def test_an_empty_name_is_refused_rather_than_stored(raw: str) -> None:
    with pytest.raises(ValueError, match="Group name is required"):
        normalize_group_name(raw)


def test_a_name_at_the_limit_survives_and_one_character_more_does_not() -> None:
    assert normalize_group_name("x" * 100) == "x" * 100

    with pytest.raises(ValueError, match="too long"):
        normalize_group_name("x" * 101)


def test_the_limit_counts_the_normalised_name_not_the_padding() -> None:
    # Padding is stripped first, so 100 characters wrapped in blanks are fine.
    assert len(normalize_group_name("   " + "y" * 100 + "   ")) == 100


# --- cwd normalisation ----------------------------------------------------


def test_a_relative_cwd_becomes_absolute(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    normalized = normalize_cwd("sub/project")

    assert Path(normalized).is_absolute()
    assert normalized == str(tmp_path / "sub" / "project")


def test_a_home_relative_cwd_is_expanded(monkeypatch, tmp_path: Path) -> None:
    # expanduser reads the environment, so the fake home has to go in through it.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    normalized = normalize_cwd("~/work/repo")

    assert normalized == str((tmp_path / "work" / "repo").resolve())
    assert "~" not in normalized


# --- the record path ------------------------------------------------------


def test_a_ordinary_ids_become_one_file_per_chat(workspace: Path) -> None:
    first = group_record_path(workspace=str(workspace), channel="feishu", chat_id="oc_123")
    second = group_record_path(workspace=str(workspace), channel="feishu", chat_id="oc_456")

    assert first != second
    assert first.name == "oc_123.json"
    assert first.parent == get_groups_dir(str(workspace)) / "feishu"


@pytest.mark.parametrize(
    "chat_id",
    ["../../windows/system32", "oc/../../../escape", "a\\b\\c", "..", ".", "oc 123*?", "%2e%2e%2fetc"],
)
def test_a_hostile_chat_id_cannot_escape_the_registry_directory(workspace: Path, chat_id: str) -> None:
    path = group_record_path(workspace=str(workspace), channel="feishu", chat_id=chat_id)

    root = get_groups_dir(str(workspace)).resolve()
    # The file must sit at groups/<channel>/<one name>.json, whatever the id contained.
    assert path.parent.parent == root, path
    assert path.parent.name == "feishu"
    # A dot-dot *inside* a name is harmless; a dot-dot *component* is the escape.
    assert ".." not in path.parts
    assert path.name.count("/") == 0 and "\\" not in path.name
    assert path.name.endswith(".json")


def test_an_id_made_entirely_of_illegal_characters_gets_a_stable_fallback(workspace: Path) -> None:
    path = group_record_path(workspace=str(workspace), channel="feishu", chat_id="///")

    assert path.name == "unknown.json"


def test_two_different_channels_keep_separate_files(workspace: Path) -> None:
    feishu = group_record_path(workspace=str(workspace), channel="feishu", chat_id="same")
    qq = group_record_path(workspace=str(workspace), channel="qq", chat_id="same")

    assert feishu != qq
    assert feishu.parent.name == "feishu" and qq.parent.name == "qq"


# --- persistence ----------------------------------------------------------


def test_saving_then_loading_round_trips_every_field(workspace: Path) -> None:
    path = save_managed_group_record(
        workspace=str(workspace),
        channel="feishu",
        chat_id="oc_9",
        owner_open_id="ou_owner",
        name="发布小组",
        cwd="sub/project",
        repo="org/app",
    )

    loaded = load_managed_group_record(workspace=str(workspace), channel="feishu", chat_id="oc_9")

    assert loaded is not None
    assert loaded["channel"] == "feishu" and loaded["chat_id"] == "oc_9"
    assert loaded["owner_open_id"] == "ou_owner"
    # The name is stored as written, not escaped into \uXXXX sequences.
    assert loaded["name"] == "发布小组"
    assert Path(loaded["cwd"]).is_absolute()
    assert loaded["repo"] == "org/app"
    assert loaded["binding_status"] == "pending_agent"
    assert loaded["metadata"] == {}
    assert datetime.fromisoformat(loaded["created_at"]).tzinfo is not None
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_an_absent_cwd_stays_absent_instead_of_becoming_the_process_directory(workspace: Path) -> None:
    save_managed_group_record(
        workspace=str(workspace),
        channel="feishu",
        chat_id="oc_nocwd",
        owner_open_id="ou",
        name="no cwd",
    )

    loaded = load_managed_group_record(workspace=str(workspace), channel="feishu", chat_id="oc_nocwd")

    assert loaded["cwd"] is None


def test_re_saving_a_group_replaces_its_record(workspace: Path) -> None:
    save_managed_group_record(
        workspace=str(workspace), channel="feishu", chat_id="oc_twice", owner_open_id="ou", name="first", binding_status="pending_agent"
    )
    save_managed_group_record(
        workspace=str(workspace), channel="feishu", chat_id="oc_twice", owner_open_id="ou", name="second", binding_status="bound"
    )

    loaded = load_managed_group_record(workspace=str(workspace), channel="feishu", chat_id="oc_twice")

    assert loaded["name"] == "second"
    assert loaded["binding_status"] == "bound"
    assert len(list((get_groups_dir(str(workspace)) / "feishu").glob("*.json"))) == 1


def test_loading_an_unknown_group_returns_none(workspace: Path) -> None:
    assert load_managed_group_record(workspace=str(workspace), channel="feishu", chat_id="never") is None


def test_the_record_is_a_frozen_value_object() -> None:
    record = ManagedGroupRecord(
        channel="feishu",
        chat_id="oc_1",
        owner_open_id="ou_1",
        name="n",
        created_at="2026-01-01T00:00:00+00:00",
    )

    assert record.binding_status == "pending_agent"
    assert record.cwd is None and record.repo is None
    assert record.metadata == {}
    with pytest.raises(FrozenInstanceError):
        record.name = "changed"  # type: ignore[misc]

    assert asdict(record)["created_at"] == "2026-01-01T00:00:00+00:00"
