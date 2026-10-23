"""Behaviour lock for the pending-tool-result summary.

The summary used to live as a private helper in ``bootstrap.runtime`` while the
IPC hosts imported it across layers.  It now lives in ``runtime.output``; these
tests pin the text so the move stays behaviour-preserving.
"""

from __future__ import annotations

from questorharness.contracts.domain.message import (
    ConversationMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _messages() -> list[ConversationMessage]:
    assistant = ConversationMessage(
        role="assistant",
        content=[
            TextBlock(text="Let me check the tree."),
            ToolUseBlock(id="toolu_1", name="Bash", input={"command": "ls"}),
        ],
    )
    user = ConversationMessage(
        role="user",
        content=[
            ToolResultBlock(tool_use_id="toolu_1", content="a.py\nb.py"),
        ],
    )
    return [assistant, user]


def test_summary_lists_tool_name_and_continue_hint():
    from questorharness.runtime.output import format_pending_tool_results

    summary = format_pending_tool_results(_messages())

    assert summary is not None
    assert summary.startswith("Pending continuation:")
    assert "Last assistant message: Let me check the tree." in summary
    assert "- Bash " in summary
    assert "a.py" in summary
    assert summary.endswith("To continue from these results, run: /continue [COUNT].")


def test_summary_returns_none_when_last_message_is_not_a_tool_result():
    from questorharness.runtime.output import format_pending_tool_results

    messages = [ConversationMessage(role="assistant", content=[TextBlock(text="done")])]

    assert format_pending_tool_results(messages) is None


def test_summary_returns_none_for_empty_history():
    from questorharness.runtime.output import format_pending_tool_results

    assert format_pending_tool_results([]) is None


def test_summary_reports_extra_results_when_truncated():
    from questorharness.runtime.output import format_pending_tool_results

    assistant = ConversationMessage(
        role="assistant",
        content=[ToolUseBlock(id=f"toolu_{i}", name="Bash", input={"command": str(i)}) for i in range(5)],
    )
    user = ConversationMessage(
        role="user",
        content=[ToolResultBlock(tool_use_id=f"toolu_{i}", content="ok") for i in range(5)],
    )

    summary = format_pending_tool_results([assistant, user])

    assert summary is not None
    assert "(+2 more tool results)" in summary
