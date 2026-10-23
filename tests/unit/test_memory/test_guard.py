"""Mirror test for ``capabilities/memory/extract/guard.py`` (plan 01, R7)."""

from __future__ import annotations

from pathlib import Path

from questorharness.capabilities.memory.extract.guard import (
    MEMORY_WRITE_TOOLS,
    has_memory_writes_since,
    validate_extraction_tool_request,
)
from questorharness.contracts.domain.message import ConversationMessage, ToolUseBlock


def _write_message(path: str, *, name: str = "write_file") -> ConversationMessage:
    return ConversationMessage(
        role="assistant",
        content=[ToolUseBlock(name=name, input={"path": path, "content": "x"})],
    )


def test_read_only_tools_are_allowed(tmp_path: Path) -> None:
    for tool in ("read_file", "grep", "glob"):
        allowed, reason = validate_extraction_tool_request(tool, {}, tmp_path)
        assert allowed is True, tool
        assert reason == "", tool


def test_bash_is_limited_to_read_only_commands(tmp_path: Path) -> None:
    ok, _ = validate_extraction_tool_request("bash", {"command": "rg memory src"}, tmp_path)
    assert ok is True

    for command in ("ls", "cat notes.txt", "git status"):
        assert validate_extraction_tool_request("bash", {"command": command}, tmp_path)[0] is True

    denied_cases = {
        "echo hi > notes.txt": "read-only",
        "rm -rf build": "read-only",
        "python -c 'print(1)'": "read-only",
        "": "read-only",
    }
    for command, hint in denied_cases.items():
        allowed, reason = validate_extraction_tool_request("bash", {"command": command}, tmp_path)
        assert allowed is False, command
        assert hint in reason, command


def test_writes_are_confined_to_the_memory_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    inside, why = validate_extraction_tool_request(
        "write_file", {"path": str(memory_dir / "note.md")}, memory_dir
    )
    outside, outside_reason = validate_extraction_tool_request(
        "write_file", {"path": "../escape.md"}, memory_dir
    )
    missing, missing_reason = validate_extraction_tool_request("edit_file", {"path": ""}, memory_dir)
    relative, _ = validate_extraction_tool_request("write_file", {"path": "note.md"}, memory_dir)

    assert inside is True and why == ""
    assert outside is False and "within" in outside_reason
    assert missing is False and "requires a path" in missing_reason
    # A bare relative name is resolved against the memory dir, so it stays inside.
    assert relative is True
    # Only an empty string counts as "no path": whitespace resolves to a name
    # under the memory dir, so a blank-looking path is not rejected here.
    assert validate_extraction_tool_request("write_file", {"path": "  "}, memory_dir)[0] is True


def test_unknown_tools_are_refused(tmp_path: Path) -> None:
    allowed, reason = validate_extraction_tool_request("browser_navigate", {"url": "x"}, tmp_path)

    assert allowed is False
    assert "browser_navigate" in reason


def test_has_memory_writes_since_scans_tool_calls(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    project = tmp_path / "repo"
    project.mkdir()

    assert MEMORY_WRITE_TOOLS == {"write_file", "edit_file"}
    assert has_memory_writes_since([_write_message("REPORT.md")], memory_dir, cwd=project) is False
    assert (
        has_memory_writes_since([_write_message(str(memory_dir / "note.md"))], memory_dir, cwd=project) is True
    )
    assert has_memory_writes_since([_write_message("note.md", name="grep")], memory_dir, cwd=project) is False
    assert has_memory_writes_since([_write_message("", name="edit_file")], memory_dir, cwd=project) is False
    # Text-only turns never count as memory writes.
    assert has_memory_writes_since([ConversationMessage.from_user_text("hi")], memory_dir) is False
