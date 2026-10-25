"""一次性生成 serve_wire 黄金帧（冻结后由 tests/ci/test_serve_wire_fixtures.py 比对）。

运行：`uv run python tests/fixtures/serve_wire/_generate.py`
产物写在本目录，逐 kind 一例；改了协议就重新生成并 review diff。
"""

from __future__ import annotations

import json
from pathlib import Path

from questorharness.bootstrap.hosts.serve.wire import (
    WireEncoder,
    approval_request_frame,
    ask_request_frame,
    stream_reset_frame,
    turn_done_frame,
    turn_started_frame,
)
from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.domain.message import ConversationMessage
from questorharness.contracts.usage import UsageSnapshot

HERE = Path(__file__).resolve().parent


def _encoder() -> WireEncoder:
    """固定上下文的编码器（turn_id/index 固定，保证可复现）。"""
    encoder = WireEncoder()
    encoder.start_turn(turn_id="turn-0001", index=1, via="studio")
    return encoder


def build_frames() -> dict[str, dict[str, object]]:
    """构造 13 帧（与 schema 的 ServerFrame 一一对应）。"""
    encoder = _encoder()
    text = encoder.encode(AssistantTextDelta(text="hello"))[0]
    message = encoder.encode(
        AssistantTurnComplete(
            message=ConversationMessage.from_user_text("done"),
            usage=UsageSnapshot(input_tokens=3, output_tokens=4),
        )
    )[0]
    dispatch = encoder.encode(ToolExecutionStarted(tool_name="bash", tool_input={"cmd": "ls"}))[0]
    result = encoder.encode(ToolExecutionCompleted(tool_name="bash", output="ok", is_error=False))[
        0
    ]
    notice = encoder.encode(StatusEvent(message="status"))[0]
    started = encoder.encode(CompactProgressEvent(phase="compact_start", trigger="auto"))[0]
    progress = encoder.encode(
        CompactProgressEvent(phase="compact_retry", trigger="auto", attempt=1)
    )[0]
    done = encoder.encode(CompactProgressEvent(phase="compact_end", trigger="auto"))[0]
    return {
        "turn_started": turn_started_frame(turn_id="turn-0001", index=1, via="studio"),
        "text": text,
        "message": message,
        "tool_dispatch": dispatch,
        "tool_result": result,
        "approval_request": approval_request_frame(
            prompt_id="approval-1",
            tool="edit",
            subject="src/app.py",
            detail="+3/-1\n@@ -1 +1,3 @@\n-old\n+new",
        ),
        "ask_request": ask_request_frame(prompt_id="ask-1", question="which file?"),
        "notice": notice,
        "compaction_started": started,
        "compaction_progress": progress,
        "compaction_done": done,
        "turn_done": turn_done_frame(
            turn_id="turn-0001", cancelled=False, outcome="completed", duration_ms=42
        ),
        "stream_reset": stream_reset_frame(reason="replay_gap", watermark=13),
    }


def main() -> int:
    """按 kind 写文件，seq 固定为 1..13。"""
    frames = build_frames()
    for index, (kind, frame) in enumerate(sorted(frames.items()), start=1):
        payload = {"seq": index, **frame}
        (HERE / f"{kind}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(f"wrote {len(frames)} fixtures to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
