"""Permission and already-written guards for memory extraction.

Moved out of ``memory/extract/__init__.py`` by plan 01 W8: deciding what the
extraction agent may touch is separate from asking the model for records.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from questorharness.contracts.domain.message import ConversationMessage, ToolUseBlock

MEMORY_WRITE_TOOLS = {"write_file", "edit_file"}


def has_memory_writes_since(
    messages: list[ConversationMessage],
    memory_dir: str | Path,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Return whether the visible turn already wrote memory files."""

    root = Path(memory_dir).expanduser().resolve()
    write_base = Path(cwd).expanduser().resolve() if cwd is not None else root
    for message in messages:
        for block in message.content:
            if not isinstance(block, ToolUseBlock):
                continue
            if block.name not in MEMORY_WRITE_TOOLS:
                continue
            raw_path = block.input.get("path") or block.input.get("file_path")
            if not raw_path:
                continue
            path = Path(str(raw_path)).expanduser()
            if not path.is_absolute():
                path = write_base / path
            try:
                path.resolve().relative_to(root)
            except ValueError:
                continue
            return True
    return False


def validate_extraction_tool_request(tool_name: str, tool_input: dict[str, Any], memory_dir: str | Path) -> tuple[bool, str]:
    """Permission guard for extraction-like agents."""

    if tool_name in {"read_file", "grep", "glob"}:
        return True, ""
    if tool_name == "bash":
        command = str(tool_input.get("command") or "")
        if _is_read_only_shell(command):
            return True, ""
        return False, "memory extraction may only run read-only shell commands"
    if tool_name in {"write_file", "edit_file"}:
        raw_path = str(tool_input.get("path") or tool_input.get("file_path") or "")
        if not raw_path:
            return False, "memory extraction write requires a path"
        root = Path(memory_dir).expanduser().resolve()
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return False, f"memory extraction writes must stay within {root}"
        return True, ""
    return False, f"memory extraction cannot use tool {tool_name}"


def _is_read_only_shell(command: str) -> bool:
    lowered = command.strip().lower()
    if not lowered:
        return False
    denied = (" > ", ">>", " rm ", " mv ", " cp ", " sed -i", " tee ", "python -c", "python3 -c")
    if any(marker in f" {lowered} " for marker in denied):
        return False
    first = lowered.split(maxsplit=1)[0]
    return first in {"ls", "pwd", "cat", "head", "tail", "rg", "grep", "find", "git", "wc", "sed", "awk", "stat"}
