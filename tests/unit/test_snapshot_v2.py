"""Snapshot v2/v3：权限/任务树/错误栈不得静默蒸发；v3 recovery_pointers typed + 旧值无锚迁移。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.memory import RecoveryPointer
from questor.contracts.state_schema import (
    ApprovalRequest,
    ApprovalStatus,
    Budget,
    Checkpoint,
    PermissionRule,
    RunStatus,
    TaskKind,
    TaskNode,
    TaskStatus,
    ToolArgsStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import Context, PermissionCtx, PermissionDecisionRecord, Run, TaskTree, ToolLedger
from questor.state.snapshot import SNAPSHOT_VERSION, SnapshotVersionError, from_snapshot, to_snapshot


def _run() -> Run:
    now = datetime.now(UTC)
    request = ApprovalRequest(
        request_id="apr-1",
        tool_call_id="tc-1",
        args_summary="write notes.md",
        risk="medium",
        reason="write without OS fence",
        created_at=now,
        expires_at=now,
        status=ApprovalStatus.APPROVED,
        decision="allow",
        decided_by="user",
        resolved_at=now,
    )
    return Run(
        run_id="run-1",
        seq=7,
        turn=2,
        status=RunStatus.RUNNING,
        budget=Budget(max_tokens=1000, approval_timeout_seconds=45),
        context=Context(
            items=(),
            compaction_floor=3,
            summary="earlier work",
            recovery_pointers=(RecoveryPointer(seq_from=1, seq_to=3, covered_hash="anchor-abc"),),
        ),
        task_tree=TaskTree(nodes=(TaskNode(id="n1", title="task", kind=TaskKind.TASK, status=TaskStatus.ACTIVE, deps=("n2",)),)),
        tool_ledger=ToolLedger(
            calls=(
                ToolCall(
                    tool_call_id="tc-1",
                    turn=2,
                    name="write",
                    args={"file_path": "notes.md"},
                    status=ToolCallStatus.AWAITING_APPROVAL,
                    args_status=ToolArgsStatus.VALID,
                    approval_request_id="apr-1",
                    permission_warnings=("no write fence",),
                    env_scrubbed=("OPENAI_API_KEY",),
                    artifact_refs=("artifact://a",),
                ),
            )
        ),
        checkpoints=(Checkpoint(cp_id="cp-1", seq=7, turn=2, kind="auto", state_digest="{}", pending_tool_calls=("tc-1",), contract_version=1),),
        permission_ctx=PermissionCtx(
            mode="plan",
            rules=(PermissionRule(id="rule-1", tool_pattern="bash", argument_pattern="rm *", action="deny"),),
            denylist=frozenset({"/secret"}),
            approvals=(request,),
            decisions=(PermissionDecisionRecord(tool_call_id="tc-1", decision="allow", decided_by="user", request_id="apr-1", at=now),),
        ),
        error_stack=(
            ErrorEntry(
                kind=ErrorKind.TIMEOUT,
                layer=ErrorLayer.TOOL,
                message="late tool",
                at_turn=1,
                hints=RecoveryHints(retryable=True),
                timestamp=now,
            ),
        ),
        created_at=now,
    )


def test_snapshot_roundtrips_full_authority() -> None:
    original = _run()
    payload = to_snapshot(original)
    assert payload["contract_version"] == SNAPSHOT_VERSION
    restored = from_snapshot(payload)
    assert restored == original
    assert restored.permission_ctx.mode == "plan"
    assert restored.permission_ctx.approvals[0].request_id == "apr-1"
    assert restored.tool_ledger.calls[0].artifact_refs == ("artifact://a",)


def test_snapshot_rejects_future_contract_version() -> None:
    payload = {**to_snapshot(_run()), "contract_version": SNAPSHOT_VERSION + 1}
    with pytest.raises(SnapshotVersionError, match="newer"):
        from_snapshot(payload)


def test_snapshot_v1_migrates_without_inventing_permission_history() -> None:
    payload = to_snapshot(_run())
    payload.pop("permission")
    payload["contract_version"] = 1
    restored = from_snapshot(payload)
    assert restored.permission_ctx.mode == "default"
    assert restored.permission_ctx.approvals == ()
    assert restored.tool_ledger.calls[0].approval_request_id == "apr-1"


def test_snapshot_v2_legacy_recovery_pointers_migrate_to_empty() -> None:
    """v2 旧快照的 pair 形 recovery_pointers 无 covered_hash 锚 → 迁移为 ()，绝不伪造锚（ADR-0024）。"""
    payload = to_snapshot(_run())
    payload["contract_version"] = 2
    payload["recovery_pointers"] = [[1, 3]]  # 旧 pair 形（v2），无锚
    restored = from_snapshot(payload)
    assert restored.context.recovery_pointers == ()
