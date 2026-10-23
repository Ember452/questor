"""Mirror test for ``capabilities/memory/session/document.py`` (plan 01, R7)."""

from __future__ import annotations

from questorharness.capabilities.memory import session
from questorharness.capabilities.memory.session import document
from questorharness.contracts.domain.message import ConversationMessage


def _messages(count: int) -> list[ConversationMessage]:
    return [ConversationMessage.from_user_text(f"message {index}") for index in range(count)]


def test_document_lists_state_sections_in_order() -> None:
    text = document.build_session_memory_document(
        _messages(2),
        tool_metadata={
            "task_focus_state": {
                "goal": "ship W8",
                "next_step": "split extract",
                "verified_state": ["guards green", "  "],
                "active_artifacts": ["TREE.md"],
            }
        },
    )

    assert text.startswith("# Session Memory\n")
    assert "## Current State\nship W8" in text
    assert "## Next Step\nsplit extract" in text
    assert "## Verified Work\n- guards green" in text
    assert "## Active Artifacts\n- TREE.md" in text
    assert "## Recent Conversation" in text
    assert "- user: message 0" in text and "- user: message 1" in text
    # Blank items are dropped rather than rendered as empty bullets.
    assert "\n- \n" not in text


def test_empty_state_and_no_messages_render_placeholders() -> None:
    text = document.build_session_memory_document([], tool_metadata=None)

    assert "(no current goal recorded)" in text
    assert "- (no recent messages)" in text
    assert "## Next Step" not in text
    assert "## Verified Work" not in text


def test_recent_lines_are_capped_and_truncation_is_noted() -> None:
    many = _messages(document.MAX_RECENT_LINES + 20)

    text = document.build_session_memory_document(many, tool_metadata={})

    # Only the last MAX_RECENT_LINES messages are kept, so message 19 is dropped
    # and the final one is present.
    assert "- user: message 19" not in text
    assert f"- user: message {document.MAX_RECENT_LINES + 19}" in text

    oversized = document.build_session_memory_document(
        _messages(1), tool_metadata={"task_focus_state": {"goal": "g" * 20000}}
    )
    assert len(oversized) <= document.MAX_SESSION_MEMORY_CHARS + 64
    assert oversized.rstrip().endswith("> Session memory was truncated to stay within budget.")


def test_compact_text_is_prefixed_or_empty() -> None:
    assert document.session_memory_to_compact_text("   ") == ""
    prepared = document.session_memory_to_compact_text("body text")
    assert prepared.startswith("Session memory checkpoint from earlier in this conversation:\n")
    assert prepared.endswith("body text")


def test_facade_reexports_the_same_objects() -> None:
    for name in session.__all__:
        source = getattr(document, name, None) or getattr(session.store, name, None)
        assert source is not None, name
        assert getattr(session, name) is source, name
