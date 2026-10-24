"""帧编码单测：7 类事件 → 13 帧，工具配对与未知类型行为。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from questorharness.bootstrap.hosts.serve.wire import WireEncoder
from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.domain.message import ConversationMessage
from questorharness.contracts.usage import UsageSnapshot


def _encoder() -> WireEncoder:
    """带 turn 上下文的编码器。"""
    encoder = WireEncoder()
    encoder.start_turn(turn_id="t1", index=1, via="studio")
    return encoder


def test_text_delta_maps_to_text_frame() -> None:
    """文本增量直通。"""
    frames = _encoder().encode(AssistantTextDelta(text="hi"))
    assert frames == [{"kind": "text", "text": "hi"}]


def test_turn_complete_flattens_blocks_and_usage() -> None:
    """回合完成帧携带内容块与用量。"""
    message = ConversationMessage.from_user_text("done")
    frames = _encoder().encode(
        AssistantTurnComplete(message=message, usage=UsageSnapshot(input_tokens=3, output_tokens=4))
    )
    assert frames[0]["kind"] == "message"
    assert frames[0]["blocks"] == [{"type": "text", "text": "done"}]
    assert frames[0]["usage"] == {"inputTokens": 3, "outputTokens": 4}


def test_unknown_content_block_degrades_visibly() -> None:
    """引擎新增块类型不得炸掉整回合：先发 warning notice，再发剩余块。"""
    message = SimpleNamespace(
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="ok")]
    )
    frames = _encoder().encode(
        AssistantTurnComplete(message=message, usage=UsageSnapshot(input_tokens=1, output_tokens=1))
    )
    assert [frame["kind"] for frame in frames] == ["notice", "message"]
    assert frames[0]["level"] == "warning"
    assert "thinking" in frames[0]["text"]
    assert frames[1]["blocks"] == [{"type": "text", "text": "ok"}]


def test_tool_started_and_completed_share_call_id() -> None:
    """工具调用与结果必须配对到同一 id。"""
    encoder = _encoder()
    started = encoder.encode(ToolExecutionStarted(tool_name="bash", tool_input={"cmd": "ls"}))
    call_id = started[0]["toolCallId"]
    completed = encoder.encode(
        ToolExecutionCompleted(tool_name="bash", output="ok", is_error=False)
    )
    assert completed[0]["toolCallId"] == call_id
    assert completed[0]["isError"] is False


def test_error_and_status_map_to_notice_levels() -> None:
    """错误与状态都走 notice，但级别不同。"""
    encoder = _encoder()
    assert encoder.encode(ErrorEvent(message="boom")) == [
        {"kind": "notice", "level": "error", "text": "boom"}
    ]
    assert encoder.encode(StatusEvent(message="ok")) == [
        {"kind": "notice", "level": "info", "text": "ok"}
    ]


def test_compaction_phases_collapse_into_three_frames() -> None:
    """9 相位归并为 started / progress / done。"""
    encoder = _encoder()
    start = encoder.encode(CompactProgressEvent(phase="compact_start", trigger="auto"))
    middle = encoder.encode(
        CompactProgressEvent(phase="context_collapse_start", trigger="auto", attempt=1)
    )
    done = encoder.encode(CompactProgressEvent(phase="compact_end", trigger="auto"))
    failed = encoder.encode(CompactProgressEvent(phase="compact_failed", trigger="manual"))
    assert start[0] == {"kind": "compaction_started", "trigger": "auto"}
    assert middle[0]["kind"] == "compaction_progress"
    assert middle[0]["attempt"] == 1
    assert done[0] == {"kind": "compaction_done", "trigger": "auto", "ok": True}
    assert failed[0] == {"kind": "compaction_done", "trigger": "manual", "ok": False}


def test_unknown_event_fails_loudly() -> None:
    """未知事件不得被静默丢弃。"""

    class Mystery:
        pass

    with pytest.raises(ValueError):
        _encoder().encode(Mystery())  # type: ignore[arg-type]
