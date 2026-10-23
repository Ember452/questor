"""Mirror test for ``capabilities/memory/extract/extraction.py`` (plan 01, R7).

The end-to-end model round trip is covered by
``test_claude_runtime_memory.py``; these cases pin the prompt, the write-down
decisions and the early exits that do not reach the API.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.memory import extract
from questorharness.capabilities.memory.extract import extraction
from questorharness.capabilities.memory.extract.records import ExtractionRecord
from questorharness.contracts.domain.message import ConversationMessage


def _record(title: str = "Note", *, scope: str = "project") -> ExtractionRecord:
    return ExtractionRecord(title=title, body="body text", scope=scope)  # type: ignore[arg-type]


def test_facade_reexports_the_same_objects_as_the_siblings() -> None:
    for name in extract.__all__:
        source = (
            getattr(extraction, name, None)
            or getattr(extract.records, name, None)
            or getattr(extract.guard, name, None)
        )
        assert source is not None, name
        assert getattr(extract, name) is source, name


def test_prompt_carries_manifest_limit_and_schema(tmp_path: Path) -> None:
    messages = [ConversationMessage.from_user_text(f"turn {index}") for index in range(15)]

    prompt = extraction.build_extraction_prompt(tmp_path, messages, max_records=2)

    assert "Extract only durable memories" in prompt
    assert "at most 2 records" in prompt
    assert '"memories"' in prompt and "JSON schema" in prompt
    # Only the last twelve turns are sent.
    assert "turn 14" in prompt
    assert "turn 2" not in prompt


def test_apply_writes_records_and_reports_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[tuple[str, str, str]] = []

    def fake_add(cwd: object, title: str, body: str, **kwargs: object) -> Path:
        written.append((title, body, str(kwargs["scope"])))
        return tmp_path / f"{title}.md"

    monkeypatch.setattr(extraction, "add_memory_entry", fake_add)

    result = extraction.apply_extraction_records(tmp_path, (_record("Alpha"), _record("Beta")))

    assert result.skipped is False and result.reason == ""
    assert [path.name for path in result.written_paths] == ["Alpha.md", "Beta.md"]
    assert written == [("Alpha", "body text", "project"), ("Beta", "body text", "project")]
    assert result.records[0].title == "Alpha"


def test_apply_skips_team_records_that_fail_the_secret_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(extraction, "check_team_memory_secrets", lambda body: "secret detected")
    monkeypatch.setattr(
        extraction,
        "add_memory_entry",
        lambda cwd, title, body, **kwargs: calls.append(title) or tmp_path / f"{title}.md",
    )

    result = extraction.apply_extraction_records(
        tmp_path, (_record("Team", scope="team"), _record("Project"))
    )

    assert calls == ["Project"]
    assert [path.name for path in result.written_paths] == ["Project.md"]
    # Both records are still reported even though one was refused.
    assert [record.title for record in result.records] == ["Team", "Project"]


def test_apply_reports_when_every_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extraction, "check_team_memory_secrets", lambda body: "secret detected")

    result = extraction.apply_extraction_records(tmp_path, (_record("Team", scope="team"),))

    assert result.skipped is True
    assert result.reason == "all records rejected"
    assert result.written_paths == ()


async def test_extract_returns_before_calling_the_model_when_the_turn_is_short(
    tmp_path: Path,
) -> None:
    class _ExplodingClient:
        def stream_message(self, request: object):  # pragma: no cover - must not run
            raise AssertionError("the API must not be called")

    result = await extraction.extract_memories_from_turn(
        cwd=tmp_path,
        api_client=_ExplodingClient(),  # type: ignore[arg-type]
        model="claude-test",
        messages=[ConversationMessage.from_user_text("only one message")],
    )

    assert result.skipped is True
    assert result.reason == "not enough messages"


async def test_extract_defers_to_writes_the_main_agent_already_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from questorharness.contracts.domain.message import ToolUseBlock

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    monkeypatch.setattr(extraction, "get_project_memory_dir", lambda cwd: memory_dir)

    class _ExplodingClient:
        def stream_message(self, request: object):  # pragma: no cover - must not run
            raise AssertionError("the API must not be called")

    messages = [
        ConversationMessage.from_user_text("write it down"),
        ConversationMessage(
            role="assistant",
            content=[ToolUseBlock(name="write_file", input={"path": str(memory_dir / "note.md")})],
        ),
    ]

    result = await extraction.extract_memories_from_turn(
        cwd=tmp_path, api_client=_ExplodingClient(), model="claude-test", messages=messages
    )

    assert result.skipped is True
    assert result.reason == "main conversation already wrote memory"
