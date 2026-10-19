"""#160：reduce 是 (run, command, now) 的纯函数——同一输入序列必产逐字节相同的状态。

旧实现 reduce 内嵌 `uuid4`（消息 id）与 `utc_now()`（created_at/started_at/completed_at/resolved_at），
使"同一命令序列两次 fold"得到不同的 id/时间戳 → 真·事件重放/多进程幂等/精确 diff 全部落空。
现在：时间戳取入参 `now`、tool_result 消息 id 由 tool_call_id 确定性派生。
"""

from __future__ import annotations

from datetime import UTC, datetime

from questor.contracts.common import new_id
from questor.contracts.events import (
    AppendAssistantMessage,
    FinalizeRun,
    MarkToolRunning,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.state.domain_state import Run
from questor.state.reduce import reduce

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _user(text: str) -> Message:
    return Message(id="m-user", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0, created_at=_NOW)


def _assistant(call_id: str) -> Message:
    return Message(
        id="m-asst",
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"file_path": "a"}),),
        seq=1,
        created_at=_NOW,
    )


def _commands(run_id: str) -> list:
    return [
        SubmitMessage(run_id=run_id, content=_user("hi")),
        AppendAssistantMessage(run_id=run_id, turn=1, message=_assistant("tc1")),
        MarkToolRunning(run_id=run_id, tool_call_id="tc1", capability="readonly", risk="low", timeout_s=1.0),
        RecordToolResult(run_id=run_id, tool_call_id="tc1", status="success", result="file body"),
        FinalizeRun(run_id=run_id, status="completed"),
    ]


def _fold(start: Run, run_id: str):
    run = start
    for command in _commands(run_id):
        run, _events = reduce(run, command, now=_NOW)
    return run


def test_reduce_is_deterministic_given_fixed_now() -> None:
    run_id = new_id("run")
    start = Run(run_id=run_id)
    a = _fold(start, run_id)
    b = _fold(start, run_id)
    assert a == b, "同一 (run, commands, now) 两次 fold 必须逐字节相同（#160）"


def test_tool_result_message_id_is_deterministic() -> None:
    run_id = new_id("run")
    run = _fold(Run(run_id=run_id), run_id)
    ids = [m.id for m in run.context.items for blk in m.content if blk.type == "tool_result"]
    assert "toolresult:tc1" in ids, f"tool_result 消息 id 未由 tool_call_id 确定性派生：{ids}"
