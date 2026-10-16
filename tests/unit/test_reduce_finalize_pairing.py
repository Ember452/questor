"""P2 审计修复 #2：任何终态都必须闭合未完成的 tool_use（C7/I1 配对不变式）。

Cancel 分支一直是对的；`FinalizeRun` 不是——failed 直接落终态，把还开着的 tool_call 留在
账本里，context 里也没有对应 tool_result。P3 做 durable resume / after_seq 续传时，这条未配对的
`tool_use` 会被原样喂回 provider（Anthropic/OpenAI 强制成对，直接 4xx），比留个 bug 更糟。
"""

from __future__ import annotations

from questor.contracts.common import new_id
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.events import AdvanceTurn, AppendAssistantMessage, FinalizeRun
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    Budget,
    ContentBlock,
    Message,
    Role,
    ToolArgsStatus,
)
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _run_with_open_tool_use() -> Run:
    run = Run(run_id=new_id("run"), budget=Budget())
    run, _ = reduce(run, AdvanceTurn(run_id=run.run_id, turn=1))
    msg = Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        seq=0,
        content=(ContentBlock(type="tool_use", tool_use_id="tc-open", name="read", input={"file_path": "a.txt"}, args_status=ToolArgsStatus.VALID, raw_input="{}"),),
    )
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=msg))
    return run


def _error() -> ErrorEntry:
    return ErrorEntry(kind=ErrorKind.CONNECTION, layer=ErrorLayer.PROVIDER, message="provider blew up", at_turn=1, hints=RecoveryHints())


def test_failed_finalize_backfills_open_tool_call() -> None:
    run = _run_with_open_tool_use()
    assert run.tool_ledger.calls[0].status in OPEN_TOOL_CALL_STATUSES

    finalized, events = reduce(run, FinalizeRun(run_id=run.run_id, status="failed", error=_error()))

    call = finalized.tool_ledger.calls[0]
    assert call.status not in OPEN_TOOL_CALL_STATUSES, call.status
    assert call.result  # 账本留下事实，不是空壳
    assert any(b.type == "tool_result" and b.tool_use_id == "tc-open" for m in finalized.context.items for b in m.content), "配对不变式 I1 被破坏"
    # failed 终态仍只有恰一个终态事件，且 seq 唯一。
    terminals = [env for env in events if env.type in {"run_failed", "run_completed", "run_cancelled"}]
    assert len(terminals) == 1
    assert len({env.seq for env in events}) == len(events)
    assert finalized.seq == max(env.seq for env in events)


def test_completed_finalize_also_backfills_defensively() -> None:
    """completed 平时由 loop 的 stop-gate 挡住，但 reduce 自身不能留下破口。"""
    run = _run_with_open_tool_use()
    finalized, events = reduce(run, FinalizeRun(run_id=run.run_id, status="completed"))
    assert finalized.tool_ledger.calls[0].status not in OPEN_TOOL_CALL_STATUSES
    assert any(b.type == "tool_result" and b.tool_use_id == "tc-open" for m in finalized.context.items for b in m.content)
    assert len(events) == 2  # 1× tool_completed 回填 + 1× run_completed


def test_finalize_without_open_calls_is_unchanged() -> None:
    """没有未闭合调用时不得多产事件（保持既有终态语义与 seq 步进）。"""
    run = Run(run_id=new_id("run"), budget=Budget())
    finalized, events = reduce(run, FinalizeRun(run_id=run.run_id, status="completed"))
    assert [env.type for env in events] == ["run_completed"]
    assert finalized.seq == run.seq + 1
