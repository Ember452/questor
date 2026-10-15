"""P1 T9 write-gate — closed_prefix never counts a half-finished tool call."""

from __future__ import annotations

from questor.contracts.common import new_id
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.state.checkpoint import closed_prefix, open_tool_use_ids


def _assistant_tool(call_id: str) -> Message:
    return Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={}),), seq=0)


def _tool_result(call_id: str) -> Message:
    return Message(id=new_id("msg"), role=Role.TOOL, content=(ContentBlock(type="tool_result", tool_use_id=call_id, text="ok"),), seq=0)


def test_prefix_advances_only_when_calls_closed() -> None:
    msgs = (_assistant_tool("tc_1"), _tool_result("tc_1"), _assistant_tool("tc_2"))
    # tc_2 is unanswered => only the first two are safe to persist.
    assert closed_prefix(msgs) == 2
    assert open_tool_use_ids(msgs) == ("tc_2",)


def test_fully_closed_returns_all() -> None:
    msgs = (_assistant_tool("tc_1"), _tool_result("tc_1"))
    assert closed_prefix(msgs) == 2
    assert open_tool_use_ids(msgs) == ()


def test_plain_text_is_immediately_closed() -> None:
    plain = Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="text", text="hi"),), seq=0)
    assert closed_prefix((plain,)) == 1
