"""Render the session-memory checkpoint document.

Moved out of ``memory/session/__init__.py`` by plan 01 W8: this half turns
conversation state into the markdown text. Reading and writing the file lives in
``store.py``.
"""

from __future__ import annotations

from questorharness.contracts.domain.message import ConversationMessage, ToolResultBlock
from questorharness.contracts.tokens import estimate_tokens

MAX_SESSION_MEMORY_CHARS = 12_000
MAX_RECENT_LINES = 80


def build_session_memory_document(
    messages: list[ConversationMessage],
    *,
    tool_metadata: dict[str, object] | None = None,
) -> str:
    """Build a compact markdown checkpoint for the current session."""

    state = tool_metadata.get("task_focus_state") if isinstance(tool_metadata, dict) else None
    goal = ""
    next_step = ""
    verified: list[str] = []
    artifacts: list[str] = []
    if isinstance(state, dict):
        goal = str(state.get("goal") or "").strip()
        next_step = str(state.get("next_step") or "").strip()
        verified = [str(item).strip() for item in state.get("verified_state", []) if str(item).strip()]
        artifacts = [str(item).strip() for item in state.get("active_artifacts", []) if str(item).strip()]

    lines = ["# Session Memory", ""]
    lines.extend(["## Current State", goal or "(no current goal recorded)", ""])
    if next_step:
        lines.extend(["## Next Step", next_step, ""])
    if verified:
        lines.extend(["## Verified Work", *[f"- {item}" for item in verified[-10:]], ""])
    if artifacts:
        lines.extend(["## Active Artifacts", *[f"- {item}" for item in artifacts[-10:]], ""])
    lines.extend(["## Recent Conversation", *_recent_message_lines(messages), ""])
    text = "\n".join(lines).strip() + "\n"
    if len(text) > MAX_SESSION_MEMORY_CHARS:
        text = text[:MAX_SESSION_MEMORY_CHARS].rsplit("\n", 1)[0]
        text += "\n\n> Session memory was truncated to stay within budget.\n"
    return text


def session_memory_to_compact_text(content: str) -> str:
    """Prepare persisted session memory for insertion across compact boundaries."""

    stripped = content.strip()
    if not stripped:
        return ""
    if estimate_tokens(stripped) > 4_000:
        stripped = stripped[:MAX_SESSION_MEMORY_CHARS].rsplit("\n", 1)[0]
    return "Session memory checkpoint from earlier in this conversation:\n" + stripped


def _recent_message_lines(messages: list[ConversationMessage]) -> list[str]:
    lines: list[str] = []
    for message in messages[-MAX_RECENT_LINES:]:
        line = _summarize_message(message)
        if line:
            lines.append(f"- {line}")
    return lines or ["- (no recent messages)"]


def _summarize_message(message: ConversationMessage) -> str:
    text = " ".join(message.text.split())
    if text:
        return f"{message.role}: {text[:220]}"
    if message.tool_uses:
        return f"{message.role}: tool calls -> {', '.join(block.name for block in message.tool_uses[:6])}"
    if any(isinstance(block, ToolResultBlock) for block in message.content):
        return f"{message.role}: tool results returned"
    return f"{message.role}: [non-text content]"
