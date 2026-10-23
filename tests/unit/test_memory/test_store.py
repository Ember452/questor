"""Mirror test for ``capabilities/memory/session/store.py`` (plan 01, R7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.memory.session import document, store
from questorharness.contracts.domain.message import ConversationMessage


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(store, "get_data_dir", lambda: root)
    return root


def test_session_memory_dir_is_project_scoped_and_created(data_root: Path, tmp_path: Path) -> None:
    cwd = tmp_path / "project"
    cwd.mkdir()

    path = store.get_session_memory_dir(cwd)

    assert path.parent == data_root / "session-memory"
    assert path.name.startswith("project-")
    assert path.is_dir()
    # Two different projects get two different directories.
    other = tmp_path / "other"
    other.mkdir()
    assert store.get_session_memory_dir(other) != path


def test_session_id_is_sanitized_into_a_file_name(data_root: Path, tmp_path: Path) -> None:
    first = store.get_session_memory_path(tmp_path, "a/b c.d-e_f")
    default = store.get_session_memory_path(tmp_path)

    assert first.name == "a_b_c.d-e_f.md"
    assert default.name == "default.md"
    assert first.parent == default.parent


def test_prepare_records_the_path_in_metadata(data_root: Path, tmp_path: Path) -> None:
    metadata: dict[str, object] = {"session_id": "s1"}

    path = store.prepare_session_memory_metadata(tmp_path, metadata)

    assert metadata["session_memory_path"] == str(path)
    # Without a session_id argument the metadata's own id is used.
    assert path.name == "s1.md"
    # And failing that, "default".
    fallback = store.prepare_session_memory_metadata(tmp_path, {})
    assert fallback.name == "default.md"


def test_reading_missing_memory_yields_empty_string(tmp_path: Path) -> None:
    assert store.get_session_memory_content(None) == ""
    assert store.get_session_memory_content("") == ""
    assert store.get_session_memory_content(tmp_path / "absent.md") == ""


def test_update_writes_the_rendered_document(data_root: Path, tmp_path: Path) -> None:
    messages = [ConversationMessage.from_user_text("keep this in mind")]

    path = store.update_session_memory_file(
        tmp_path, messages, tool_metadata={"task_focus_state": {"goal": "finish W8"}}
    )
    content = store.get_session_memory_content(path)

    assert path.exists()
    assert content == document.build_session_memory_document(
        messages, tool_metadata={"task_focus_state": {"goal": "finish W8"}}
    )
    assert "finish W8" in content
    assert "- user: keep this in mind" in content
