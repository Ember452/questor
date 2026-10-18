"""D-P7-C 选型①（ADR-0034）：`message_completed` additive 带**有界** `final_text`，让重连仅靠事件流即恢复定稿文本。

判红点：
- `EXTERNAL_EVENT_FIELDS[MESSAGE_COMPLETED]` 现含 final_text/item_id/truncated（原仅 message_id）。
- reduce 派生 `final_text` = 消息可见文本（text 块拼接），超上限截断并置 `truncated=True`。
- `project()` 把 final_text 透传到对外帧（前端据此重放渲染）。
- **C20 第二载体红线**：final_text 是协议字段，**绝不进带外投影** fields。
- **未定稿的半条在途 delta 仍补不回**：本 additive 只覆盖定稿消息（`message_completed` 边界），不假装补齐 streamed 半成品。
"""

from __future__ import annotations

from questor.contracts.events import Envelope, EventType
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.events import EXTERNAL_EVENT_FIELDS, project
from questor.observability.projection import project as obs_project
from questor.state import reduce

_LIMIT = 8192


def _msg(text: str) -> Message:
    return Message(id="msg_1", role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=0)


def test_whitelist_carries_final_text() -> None:
    allowed = EXTERNAL_EVENT_FIELDS[EventType.MESSAGE_COMPLETED]
    assert allowed is not None
    assert {"message_id", "item_id", "final_text", "truncated"} <= set(allowed), allowed


def test_short_message_full_final_text() -> None:
    data = reduce._message_completed_data(_msg("hello world"))  # noqa: SLF001
    assert data["final_text"] == "hello world"
    assert data["item_id"] == "msg_1"
    assert data["truncated"] is False


def test_long_message_final_text_is_bounded_and_flagged() -> None:
    big = "汉" * (_LIMIT + 10)  # 非 ASCII，确保按字符数截断仍在界内
    data = reduce._message_completed_data(_msg(big))  # noqa: SLF001
    assert len(data["final_text"]) <= _LIMIT
    assert data["truncated"] is True


def test_project_forwards_final_text() -> None:
    internal = Envelope(v=1, seq=2, run_id="r", type=EventType.MESSAGE_COMPLETED, data={"message_id": "m", "final_text": "hi", "truncated": False})
    projected = project(internal)
    assert projected is not None and projected.data.get("final_text") == "hi"


def test_final_text_not_in_out_of_band_projection() -> None:
    """C20：定稿正文进事件协议，但绝不进带外日志 fields。"""
    env = Envelope(v=1, seq=3, run_id="r", type=EventType.MESSAGE_COMPLETED, data={"message_id": "m", "final_text": "SECRET body", "truncated": False})
    entry = obs_project(env)
    assert entry is not None
    assert "final_text" not in entry.fields, entry.fields
