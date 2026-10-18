#!/usr/bin/env python3
"""Replay-determinism invariant guard (ADR-0005/0020/0021; HARD C2/C5/C7/I4).

这是 P3 续跑正确性的**地基证明**：对同一条 Command 序列，
"连续 reduce 到底" 与 "在某个 split 处落 checkpoint、from_snapshot 重建、再继续 reduce 尾部"
必须得到**一致的权威状态**（seq/turn/status、tool_ledger、context 的 tool_use↔tool_result 配对、
permission approvals/decisions）。这正是 ROADMAP "重启能续跑/回放" 所依赖的性质，也守住
"恢复=最近快照+重放其后事件" 不因快照有损而漂移。

它比较的是权威**骨架**（忽略 new_id 生成的 message id 与 utc_now 时间戳这类非确定字段，
只比 role/block 形状、tool_call_id、审批 request_id、status、seq）——因此对随机 id/时钟免疫，
只对真正的状态漂移敏感。

- ``check``：跑全部 fixture，任一 (full != snapshot+tail) 即判红。
- ``--self-test``：既证绿（健康 fixture 通过），又证红（截断尾部/破坏配对必须被抓到）（C15）。
- **fail-on-empty**：没有任何 fixture 视为配置错误（exit 2），不是通过。

Usage:
    uv run python scripts/check_replay_determinism.py
    uv run python scripts/check_replay_determinism.py --self-test
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from questor.contracts.events import (
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Command,
    FinalizeRun,
    MarkToolValidated,
    RecordToolResult,
    ReportChildTerminal,
    RequestApproval,
    ResolveApproval,
    SpawnSubagent,
    SubmitMessage,
    UpdateTaskTree,
)
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role, TaskKind, TaskNode, ToolArgsStatus
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot, to_snapshot

_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _user() -> Message:
    return Message(id="u0", role=Role.USER, seq=0, content=(ContentBlock(type="text", text="go"),))


def _assistant_tool_use(tc: str, turn: int) -> Message:
    return Message(
        id=f"a{turn}",
        role=Role.ASSISTANT,
        seq=turn,
        content=(ContentBlock(type="tool_use", tool_use_id=tc, name="read", input={"file_path": "x"}, args_status=ToolArgsStatus.VALID, raw_input="{}"),),
    )


def _fixture_approve() -> tuple[Run, list[Command], int]:
    rid = "r_ok"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tc1", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tc1"),
        RequestApproval(run_id=rid, tool_call_id="tc1", request_id="req1", args_summary="read x", risk="low", reason="ask", expires_at=_FUTURE),
        ResolveApproval(run_id=rid, request_id="req1", decision="allow", decided_by="user"),
        RecordToolResult(run_id=rid, tool_call_id="tc1", status="success", result="ok"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 恰在审批挂起处（含未闭合 tool_use）


def _fixture_cancel_backfill() -> tuple[Run, list[Command], int]:
    rid = "r_cancel"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tc9", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tc9"),
        Cancel(run_id=rid, reason=CancelReason.USER),  # 必须回填未闭合 tool_use（C7）
    ]
    return run, cmds, 3  # split 在 open 调用尚存处


def _fixture_multi_turn() -> tuple[Run, list[Command], int]:
    rid = "r_multi"
    run = Run(run_id=rid, budget=Budget(max_turns=5))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tcA", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tcA"),
        RecordToolResult(run_id=rid, tool_call_id="tcA", status="success", result="done"),
        AdvanceTurn(run_id=rid, turn=2),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 在 turn1 工具闭合、turn2 未起处


def _fixture_spawn_report() -> tuple[Run, list[Command], int]:
    """P8：父 update-tree→spawn→report 全走 reduce；验证 task_tree（含 assigned_run_id）跨快照 round-trip 确定。"""
    rid = "r_spawn"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    sub_node = TaskNode(id="n1", title="child task", kind=TaskKind.SUBAGENT)
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        UpdateTaskTree(run_id=rid, upsert=(sub_node,)),
        SpawnSubagent(run_id=rid, node_id="n1", child_run_id="r-child-1", spawn_key="spawn:n1:1"),
        ReportChildTerminal(run_id=rid, child_run_id="r-child-1", node_id="n1", terminal_status="completed"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 4  # split 恰在 spawn 之后、report 之前（task_tree 含 active+assigned_run_id）


def _fixture_multi_child_report() -> tuple[Run, list[Command], int]:
    """P8：父 spawn 两子、分别 report（一个 done 一个 failed）；验证多子 task_tree 跨快照 round-trip 确定。"""
    rid = "r_multi_child"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    nodes = (TaskNode(id="c1", title="c1", kind=TaskKind.SUBAGENT), TaskNode(id="c2", title="c2", kind=TaskKind.SUBAGENT))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        UpdateTaskTree(run_id=rid, upsert=nodes),
        SpawnSubagent(run_id=rid, node_id="c1", child_run_id="rc1", spawn_key="s:c1"),
        SpawnSubagent(run_id=rid, node_id="c2", child_run_id="rc2", spawn_key="s:c2"),
        ReportChildTerminal(run_id=rid, child_run_id="rc1", node_id="c1", terminal_status="completed"),
        ReportChildTerminal(run_id=rid, child_run_id="rc2", node_id="c2", terminal_status="failed"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 在第一子 report 后、第二子 report 前（task_tree 半更新态）


FIXTURES: list[tuple[str, Callable[[], tuple[Run, list[Command], int]]]] = [
    ("approve", _fixture_approve),
    ("cancel-backfill", _fixture_cancel_backfill),
    ("multi-turn", _fixture_multi_turn),
    ("spawn-report", _fixture_spawn_report),
    ("multi-child-report", _fixture_multi_child_report),
]


def _replay_full(run: Run, cmds: list[Command]) -> Run:
    for cmd in cmds:
        run, _ = reduce(run, cmd)
    return run


def _replay_snapshot_tail(run: Run, cmds: list[Command], split: int) -> Run:
    for cmd in cmds[:split]:
        run, _ = reduce(run, cmd)
    # 落 checkpoint → 重建权威状态（模拟进程重启后从持久态出发）。
    run = from_snapshot(to_snapshot(run))
    for cmd in cmds[split:]:
        run, _ = reduce(run, cmd)
    return run


def _canonical(run: Run) -> dict:
    """权威骨架：忽略随机 message id / 时间戳，只对状态漂移敏感。"""
    items = tuple(
        (m.role.value, tuple(b.type for b in m.content), tuple(b.tool_use_id or "" for b in m.content), tuple((b.text or "") for b in m.content))
        for m in run.context.items
    )
    calls = tuple(sorted((c.tool_call_id, c.name, c.status.value) for c in run.tool_ledger.calls))
    approvals = tuple(sorted((a.request_id, a.tool_call_id, a.status.value, a.decision or "") for a in run.permission_ctx.approvals))
    # P8：task_tree 必须进权威骨架——否则 DAG/spawn 状态漂移全绿（最危险的静默错，ADR-0037/0038）。
    task_tree = tuple(
        sorted(
            (n.id, n.status.value, n.kind.value, n.parent_id or "", tuple(n.deps), n.assigned_run_id or "")
            for n in run.task_tree.nodes
        )
    )
    return {
        "status": run.status.value,
        "turn": run.turn,
        "seq": run.seq,
        "cancel": run.cancel_reason.value if run.cancel_reason else None,
        "mode": run.permission_ctx.mode,
        "n_decisions": len(run.permission_ctx.decisions),
        "errors": len(run.error_stack),
        "items": items,
        "calls": calls,
        "approvals": approvals,
        "task_tree": task_tree,
    }


def _check_one(name: str, factory: Callable[[], tuple[Run, list[Command], int]]) -> list[str]:
    run, cmds, split = factory()
    full = _canonical(_replay_full(run, cmds))
    tail = _canonical(_replay_snapshot_tail(run, cmds, split))
    problems: list[str] = []
    if full != tail:
        diff_keys = sorted(k for k in full if full[k] != tail[k])
        problems.append(f"{name}: snapshot+tail diverges from continuous replay in {diff_keys}")
    return problems


def check() -> int:
    if not FIXTURES:
        print("no fixtures defined (fail-on-empty)", file=sys.stderr)
        return 2
    problems = [p for name, factory in FIXTURES for p in _check_one(name, factory)]
    for msg in problems:
        print(msg, file=sys.stderr)
    if problems:
        return 1
    print(f"replay determinism OK: {len(FIXTURES)} fixtures — snapshot+tail == continuous reduce")
    return 0


def _self_test_green() -> bool:
    return not any(_check_one(name, factory) for name, factory in FIXTURES)


def _self_test_red() -> bool:
    """破坏样例：只落快照、丢掉尾部再比较，权威 seq/状态必然落后 → 守卫必须判红。"""
    run, cmds, split = _fixture_approve()
    snap_only = from_snapshot(to_snapshot(_replay_full(run, cmds[:split])))
    return _canonical(snap_only) != _canonical(_replay_full(run, cmds))


def self_test() -> int:
    green = _self_test_green()
    red = _self_test_red()
    ok = green and red
    print(f"self-test: healthy-green={green} truncated-caught={red}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    raise SystemExit(main())
