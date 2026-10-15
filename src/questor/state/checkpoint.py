"""L1 checkpoint write-gate (design/01 §5; R03 C-1).

Pure helpers to decide *what is safe to persist*: the durable store must never
hold a half-finished tool call, so we only flush up to the longest prefix whose
every ``tool_use`` already has a matching ``tool_result``. This is my own
implementation of that invariant (not a port of any reference code).
"""

from __future__ import annotations

from questor.contracts.state_schema import ContentBlock, Message


def closed_prefix(messages: tuple[Message, ...]) -> int:
    """Length of the longest prefix in which every ``tool_use`` is answered.

    Scans messages in order, tracking the set of open ``tool_use`` ids; the cut
    advances to each position where that set is momentarily empty. A trailing
    unanswered ``tool_use`` is held back (the caller flushes it on the next turn).
    """
    open_ids: set[str] = set()
    cut = 0
    for index, message in enumerate(messages):
        for block in message.content:
            _track(block, open_ids)
        if not open_ids:
            cut = index + 1
    return cut


def _track(block: ContentBlock, open_ids: set[str]) -> None:
    if block.type == "tool_use" and block.tool_use_id:
        open_ids.add(block.tool_use_id)
    elif block.type == "tool_result" and block.tool_use_id:
        open_ids.discard(block.tool_use_id)


def open_tool_use_ids(messages: tuple[Message, ...]) -> tuple[str, ...]:
    """Tool_use ids still unanswered — stored on a checkpoint for later repair."""
    open_ids: set[str] = set()
    for message in messages:
        for block in message.content:
            _track(block, open_ids)
    return tuple(sorted(open_ids))
