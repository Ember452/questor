"""T19：checkpoint/HITL resume —— 审批/权限状态不在 checkpoint 静默蒸发（ADR-0014/0016）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from questor.contracts.common import new_id, utc_now
from questor.contracts.events import AdvanceTurn, AppendAssistantMessage, MarkToolValidated, RequestApproval, SetPermissionMode
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
from questor.kernel.recovery import resume_run
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot


def _awaiting_run(*, expires_at) -> Run:
    run = Run(run_id=new_id("run"), budget=Budget())
    run, _ = reduce(run, AdvanceTurn(run_id=run.run_id, turn=1))
    msg = Message(id=new_id("msg"), role=Role.ASSISTANT, seq=0, content=(ContentBlock(type="tool_use", tool_use_id="tc1", name="write", input={"file_path": "x.txt", "content": "hi"}, args_status=ToolArgsStatus.VALID, raw_input="{}"),))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=msg))
    run, _ = reduce(run, MarkToolValidated(run_id=run.run_id, tool_call_id="tc1"))
    run, _ = reduce(run, RequestApproval(run_id=run.run_id, tool_call_id="tc1", request_id="apr-1", args_summary="write x.txt", risk="high", reason="no write fence", expires_at=expires_at))
    return run


async def _checkpoint(store, run) -> None:
    await store.save_checkpoint({"cp_id": new_id("cp"), "run_id": run.run_id, "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": ["tc1"]})


async def test_awaiting_approval_survives_restart(tmp_path) -> None:
    future = utc_now() + timedelta(seconds=300)
    original = _awaiting_run(expires_at=future)
    assert original.status is RunStatus.AWAITING_APPROVAL

    store = await SQLiteStore(str(tmp_path / "a.db")).connect()
    await _checkpoint(store, original)
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "a.db")).connect()
    resumed = await resume_run(reopened, original.run_id)
    await reopened.close()

    assert resumed is not None
    assert resumed.status is RunStatus.AWAITING_APPROVAL
    approval = next(a for a in resumed.permission_ctx.approvals if a.request_id == "apr-1")
    assert approval.status is ApprovalStatus.PENDING
    assert approval.expires_at == future  # expiry 精确保留
    call = next(c for c in resumed.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.AWAITING_APPROVAL  # 未被自动执行


async def test_expired_approval_closes_on_resume_not_silently(tmp_path) -> None:
    # 快照时审批仍未过期；重启后时钟已越过 expires_at —— 恢复必须显式闭合，不静默丢弃/复活。
    original = _awaiting_run(expires_at=utc_now() + timedelta(seconds=2))
    store = await SQLiteStore(str(tmp_path / "b.db")).connect()
    await _checkpoint(store, original)
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "b.db")).connect()
    resumed = await resume_run(reopened, original.run_id, now=utc_now() + timedelta(seconds=3600))
    await reopened.close()

    approval = next(a for a in resumed.permission_ctx.approvals if a.request_id == "apr-1")
    assert approval.status is ApprovalStatus.EXPIRED
    assert approval.decision == "deny"
    call = next(c for c in resumed.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.DENIED


async def test_permission_mode_and_decisions_round_trip(tmp_path) -> None:
    run = _awaiting_run(expires_at=utc_now() + timedelta(seconds=300))
    run, _ = reduce(run, SetPermissionMode(run_id=run.run_id, mode="full_auto", changed_by="user"))
    assert run.permission_ctx.mode == "full_auto"

    store = await SQLiteStore(str(tmp_path / "c.db")).connect()
    await _checkpoint(store, run)
    await store.close()

    reopened = await SQLiteStore(str(tmp_path / "c.db")).connect()
    resumed = await resume_run(reopened, run.run_id, now=datetime.now(run.created_at.tzinfo))
    await reopened.close()

    assert resumed.permission_ctx.mode == "full_auto"
    # full_auto 是"未来 intent"，不得把当前这条仍 pending 的 write 审批自动放行/蒸发（历史不回溯）。
    approval = next(a for a in resumed.permission_ctx.approvals if a.request_id == "apr-1")
    assert approval.status is ApprovalStatus.PENDING
