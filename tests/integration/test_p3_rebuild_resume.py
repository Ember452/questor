"""P3 T10/T11/T13：重建续跑 —— 快照权威 + seq 对齐 + 幂等 re-dispatch（ADR-0020/0021）。

覆盖 ROADMAP P3 判据"kill 后重启续跑"的核心：从持久态重建 AWAITING/PENDING run、审批不蒸发、
续跑不重复副作用、未批准的危险写绝不被 resume 静默放行、终态幂等。用真实 SQLiteStore +
InProcessEventBus + DefaultTurnLoop 全接线；OS 级真杀见 test_p3_kill_resume.py。
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest

from questor.contracts.common import new_id, utc_now
from questor.contracts.events import (
    AdvanceTurn,
    AppendAssistantMessage,
    FinalizeRun,
    MarkToolValidated,
    RequestApproval,
    ResolveApproval,
    SubmitMessage,
)
from questor.contracts.permission import PermissionDecision
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import (
    ApprovalStatus,
    Budget,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolArgsStatus,
    ToolCallStatus,
)
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec
from questor.kernel.durability import resume_and_drive
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permission_policy import PermissionEvaluation, PermissionOutcome
from questor.kernel.recovery import NoIntactCheckpointError, rebuild_run, resume_run
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot


class _AlwaysAsk:
    def evaluate(self, evaluation: PermissionEvaluation) -> PermissionOutcome:
        return PermissionOutcome(decision=PermissionDecision.ASK, reason="test approval required", args_summary=evaluation.tool_name)


class _RecordingTool(Tool):
    """执行一次就把 'x' 追加到 out.txt；used 计数证明 resume 不重复副作用。"""

    def __init__(self, tmp_path: Path) -> None:
        self._out = tmp_path / "out.txt"
        self.used = 0
        self.spec = ToolSpec(
            name="record",
            description="append marker once",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            capability=Capability.WRITE,
            risk=Risk.MEDIUM,
            read_only=False,
        )

    def available(self) -> bool:
        return True

    async def execute(self, args, ctx: ToolContext) -> ToolResult:  # noqa: ANN001
        self.used += 1
        self._out.write_text(self._out.read_text() + "x" if self._out.exists() else "x", encoding="utf-8")
        return ToolResult(status="success", result="recorded")


_ANSWER = [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]


def _build_loop(tmp_path: Path, tool: Tool, store) -> DefaultTurnLoop:
    bus = InProcessEventBus(store)
    return DefaultTurnLoop(
        provider=ScriptedProvider([_ANSWER]),
        policy=ReActPolicy(),
        permission=_AlwaysAsk(),
        bus=bus,
        tool_for=lambda name: tool if name == "record" else None,
        tools=(tool,),
        store=store,
        workspace_root=tmp_path,
        cancel_event=asyncio.Event(),
    )


def _tool_use_message() -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        seq=0,
        content=(ContentBlock(type="tool_use", tool_use_id="tc", name="record", input={}, args_status=ToolArgsStatus.VALID, raw_input="{}"),),
    )


async def _awaiting_run(tmp_path: Path) -> Run:
    """reduce 到 awaiting_approval：全量快照含 tool_use + 审批（截断会抹掉它，见 ADR-0020）。"""
    run = Run(run_id=new_id("run"), budget=Budget(max_turns=5))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)))
    run, _ = reduce(run, AdvanceTurn(run_id=run.run_id, turn=1))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_tool_use_message()))
    run, _ = reduce(run, MarkToolValidated(run_id=run.run_id, tool_call_id="tc"))
    run, _ = reduce(run, RequestApproval(run_id=run.run_id, tool_call_id="tc", request_id="apr1", args_summary="record", risk="medium", reason="approval required", expires_at=utc_now() + timedelta(hours=1)))
    return run


async def _persist(store, run, *, pending: tuple[str, ...] = ()) -> None:
    await store.append(run.run_id, ({"type": "run_started", "data": {"run_id": run.run_id}},))
    await store.save_checkpoint(
        {"cp_id": new_id("cp"), "run_id": run.run_id, "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": __import__("json").dumps(to_snapshot(run)), "pending": list(pending)}
    )


async def test_rebuild_run_preserves_awaiting_and_aligns_seq(tmp_path: Path) -> None:
    original = await _awaiting_run(tmp_path)
    store = await SQLiteStore(str(tmp_path / "a.db")).connect()
    await _persist(store, original)
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "a.db")).connect()
    rebuilt = await rebuild_run(reopened, original.run_id)
    await reopened.close()

    assert rebuilt is not None
    assert rebuilt.status is RunStatus.AWAITING_APPROVAL
    call = next(c for c in rebuilt.tool_ledger.calls if c.tool_call_id == "tc")
    assert call.status is ToolCallStatus.AWAITING_APPROVAL  # 未被自动执行/抹掉
    approval = next(a for a in rebuilt.permission_ctx.approvals if a.request_id == "apr1")
    assert approval.status is ApprovalStatus.PENDING
    # seq 对齐到 log head（快照 seq 落后于已 append 事件时抬高，不复用旧号）
    assert rebuilt.seq >= original.seq
    # 向后兼容入口等价
    r2 = await resume_run(await SQLiteStore(str(tmp_path / "a.db")).connect(), original.run_id)
    assert r2 is not None and r2.status is RunStatus.AWAITING_APPROVAL


async def test_resume_allow_executes_tool_once(tmp_path: Path) -> None:
    original = await _awaiting_run(tmp_path)
    store = await SQLiteStore(str(tmp_path / "b.db")).connect()
    await _persist(store, original)
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "b.db")).connect()
    rebuilt = await rebuild_run(reopened, original.run_id)
    tool = _RecordingTool(tmp_path)
    loop = _build_loop(tmp_path, tool, reopened)
    controller = RunController(rebuilt)
    # 人类批准走同一 Command Inbox（C16）：先投 allow，再交回唯一 loop 续跑。
    await controller.submit(ResolveApproval(run_id=rebuilt.run_id, request_id="apr1", decision="allow", decided_by="user"), source="test", idempotency_key="apr1")
    run = await loop.drive_controller(controller)
    await reopened.close()

    assert run.status is RunStatus.COMPLETED
    assert tool.used == 1  # 恰好执行一次，无重复副作用
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "x"
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc")
    assert call.status is ToolCallStatus.SUCCESS
    # provider 配对完整：context 同时含 tool_use 与 tool_result
    has_use = any(b.type == "tool_use" and b.tool_use_id == "tc" for m in run.context.items for b in m.content)
    has_result = any(b.type == "tool_result" and b.tool_use_id == "tc" for m in run.context.items for b in m.content)
    assert has_use and has_result


async def test_resume_pending_call_reasks_and_never_auto_executes(tmp_path: Path) -> None:
    """崩溃在权限判定前（PENDING）：resume 必须重走权限，绝不绕过 ask 静默执行（安全不变式）。"""
    run = Run(run_id=new_id("run"), budget=Budget(max_turns=5, approval_timeout_seconds=0.05))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)))
    run, _ = reduce(run, AdvanceTurn(run_id=run.run_id, turn=1))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_tool_use_message()))  # call PENDING

    store = await SQLiteStore(str(tmp_path / "c.db")).connect()
    await _persist(store, run, pending=("tc",))
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "c.db")).connect()
    rebuilt = await rebuild_run(reopened, run.run_id)
    tool = _RecordingTool(tmp_path)
    loop = _build_loop(tmp_path, tool, reopened)  # 审批超时 → 拒绝（approval_timeout_seconds 默认）
    controller = RunController(rebuilt)
    resumed = await loop.drive_controller(controller)
    await reopened.close()

    assert resumed.status is RunStatus.COMPLETED
    assert tool.used == 0  # 无人批准 → 危险写绝不因 resume 而执行
    call = next(c for c in resumed.tool_ledger.calls if c.tool_call_id == "tc")
    assert call.status is ToolCallStatus.DENIED


async def test_resume_and_drive_idempotent_on_terminal(tmp_path: Path) -> None:
    run = Run(run_id=new_id("run"), budget=Budget(max_turns=5))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)))
    run, _ = reduce(run, FinalizeRun(run_id=run.run_id, status="completed", exit_reason="answered"))

    store = await SQLiteStore(str(tmp_path / "d.db")).connect()
    await _persist(store, run)
    tool = _RecordingTool(tmp_path)
    loop = _build_loop(tmp_path, tool, store)

    done = await resume_and_drive(loop, store, run.run_id)
    assert done is not None and done.status is RunStatus.COMPLETED
    assert tool.used == 0  # 终态 run 续跑是空操作（不重跑任何工具）
    await store.close()


async def test_resume_unknown_run_returns_none(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "e.db")).connect()
    tool = _RecordingTool(tmp_path)
    loop = _build_loop(tmp_path, tool, store)
    assert await resume_and_drive(loop, store, "nope") is None
    await store.close()


async def test_rebuild_falls_back_to_previous_intact_checkpoint(tmp_path: Path) -> None:
    """A1：最新快照损坏时回退次近完好快照（权威状态靠快照，不靠 reduce 回灌输出事件，C5）。"""
    store = await SQLiteStore(str(tmp_path / "fb.db")).connect()
    run = Run(run_id="run_fb", budget=Budget())
    await store.append("run_fb", ({"type": "run_started", "data": {}},))
    await store.save_checkpoint({"cp_id": "cp1", "run_id": "run_fb", "seq": 1, "turn": 0, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": []})
    # 一个更新的、损坏的快照（latest_checkpoint 会先取到它）。
    await store.save_checkpoint({"cp_id": "cp9", "run_id": "run_fb", "seq": 9, "turn": 0, "kind": "auto", "state_digest": "{not valid json", "pending": []})

    rebuilt = await rebuild_run(store, "run_fb")  # 必须跳过 cp9、用 cp1
    assert rebuilt is not None and rebuilt.run_id == "run_fb"
    await store.close()


async def test_rebuild_fail_closed_when_all_checkpoints_corrupt(tmp_path: Path) -> None:
    """A1：有快照但全部损坏 → fail-closed 抛错，绝不静默当"未知 run"。无快照才返回 None。"""
    store = await SQLiteStore(str(tmp_path / "bad.db")).connect()
    await store.save_checkpoint({"cp_id": "cpX", "run_id": "run_bad", "seq": 3, "turn": 0, "kind": "auto", "state_digest": "{corrupt", "pending": []})
    with pytest.raises(NoIntactCheckpointError):
        await rebuild_run(store, "run_bad")
    # 真无快照（未知/未落库）仍是 None，不是抛错。
    assert await rebuild_run(store, "run_never") is None
    await store.close()
