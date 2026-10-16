"""P0 DoD —— 接口骨架上的构造不变式成立（design/01/02）。

只断言*形状*守卫；reduce/循环的运行时行为属 P1。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id, validate_json_object
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.events import (
    Cancel,
    Envelope,
    EventType,
    ExpireApproval,
    MarkToolRunning,
    MarkToolValidated,
    RequestApproval,
    ResolveApproval,
    SetPermissionMode,
)
from questor.contracts.state_schema import (
    CLOSED_TOOL_CALL_STATUSES,
    OPEN_TOOL_CALL_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    CancelReason,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolArgsStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.contracts.tool import Capability
from questor.state.domain_state import PermissionCtx, Run


def test_run_terminal_requires_completed_at() -> None:
    with pytest.raises(ValueError, match="completed_at"):
        Run(run_id=new_id("run"), status=RunStatus.COMPLETED)


def test_run_cancelled_requires_reason() -> None:
    ts = datetime.now()  # naive on purpose -> must fail ts check OR reason check first
    with pytest.raises(ValueError):
        Run(run_id=new_id("run"), status=RunStatus.CANCELLED, completed_at=ts)


def test_run_non_terminal_cannot_have_completed_at() -> None:
    with pytest.raises(ValueError, match="non-terminal"):
        Run(run_id=new_id("run"), status=RunStatus.RUNNING, completed_at=datetime.now())


def test_message_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Message(
            id=new_id("msg"), role=Role.USER, content=(), seq=0, created_at=datetime(2020, 1, 1)
        )


def test_message_negative_seq_rejected() -> None:
    with pytest.raises(ValueError, match="Message.seq"):
        Message(id=new_id("msg"), role=Role.USER, content=(), seq=-1)


def test_envelope_negative_seq_rejected() -> None:
    with pytest.raises(ValueError, match="Envelope.seq"):
        Envelope(v=1, seq=-1, run_id=new_id("run"), type="run_started", data={})


def test_error_entry_rejects_naive_timestamp() -> None:
    hints = RecoveryHints(retryable=True)
    with pytest.raises(ValueError, match="timezone-aware"):
        ErrorEntry(
            kind=ErrorKind.TIMEOUT,
            layer=ErrorLayer.PROVIDER,
            message="boom",
            at_turn=1,
            hints=hints,
            timestamp=datetime(2020, 1, 1),
        )


def test_cancel_command_carries_reason() -> None:
    cmd = Cancel(run_id=new_id("run"), reason=CancelReason.NO_PROGRESS)
    assert cmd.type == "cancel"
    assert cmd.reason is CancelReason.NO_PROGRESS


def test_read_tool_is_readonly_capability() -> None:
    assert ReadTool.spec.name == "read"
    assert ReadTool.spec.read_only is True
    assert ReadTool.spec.capability is Capability.READONLY
    assert ReadTool.spec.parallel_safe is False  # placeholder only until P5


def test_validate_json_object_blocks_nan() -> None:
    with pytest.raises(ValueError, match="JSON-safe"):
        validate_json_object({"x": float("nan")}, "payload")


def test_p2_tool_call_lifecycle_locks_every_state() -> None:
    """P2 状态机必须可持久化，不能把审批/运行中状态退回为内存变量。"""
    assert {status.value for status in ToolCallStatus} == {
        "pending",
        "validated",
        "awaiting_approval",
        "ready",
        "running",
        "success",
        "error",
        "critical_error",
        "timed_out",
        "cancelled",
        "denied",
    }
    assert OPEN_TOOL_CALL_STATUSES == {
        ToolCallStatus.PENDING,
        ToolCallStatus.VALIDATED,
        ToolCallStatus.AWAITING_APPROVAL,
        ToolCallStatus.READY,
        ToolCallStatus.RUNNING,
    }
    assert CLOSED_TOOL_CALL_STATUSES == {
        ToolCallStatus.SUCCESS,
        ToolCallStatus.ERROR,
        ToolCallStatus.CRITICAL_ERROR,
        ToolCallStatus.TIMED_OUT,
        ToolCallStatus.CANCELLED,
        ToolCallStatus.DENIED,
    }
    assert not OPEN_TOOL_CALL_STATUSES & CLOSED_TOOL_CALL_STATUSES


def test_p2_contract_lifecycle_supports_args_and_approval_states() -> None:
    assert {status.value for status in ToolArgsStatus} == {"valid", "invalid", "missing"}
    assert {status.value for status in ApprovalStatus} == {
        "pending",
        "approved",
        "denied",
        "expired",
        "cancelled",
    }


def test_approval_request_identity_enforces_time_and_resolution_invariants() -> None:
    now = datetime.now(UTC)
    request = ApprovalRequest(
        request_id=new_id("apr"),
        tool_call_id=new_id("tc"),
        args_summary="remove 3 files under src/",
        risk="high",
        reason="destructive command",
        created_at=now,
        expires_at=now.replace(microsecond=now.microsecond + 1),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = ApprovalStatus.APPROVED  # type: ignore[misc]
    with pytest.raises(ValueError, match="timezone-aware"):
        ApprovalRequest(
            request_id="a",
            tool_call_id="t",
            args_summary="x",
            risk="low",
            reason="test",
            created_at=datetime(2026, 1, 1),
            expires_at=now,
        )
    with pytest.raises(ValueError, match="expires_at"):
        ApprovalRequest(
            request_id="a",
            tool_call_id="t",
            args_summary="x",
            risk="low",
            reason="test",
            created_at=now,
            expires_at=now.replace(microsecond=now.microsecond - 1),
        )
    with pytest.raises(ValueError, match="resolved ApprovalRequest"):
        ApprovalRequest(
            request_id="a",
            tool_call_id="t",
            args_summary="x",
            risk="low",
            reason="test",
            created_at=now,
            expires_at=now,
            status=ApprovalStatus.APPROVED,
        )


def test_permission_context_persists_pending_approvals() -> None:
    now = datetime.now(UTC)
    request = ApprovalRequest(
        request_id="apr-1",
        tool_call_id="tc-1",
        args_summary="write file",
        risk="medium",
        reason="no write fence",
        created_at=now,
        expires_at=now,
    )
    ctx = PermissionCtx(approvals=(request,))
    assert ctx.approvals[0].request_id == "apr-1"
    assert ctx.approvals[0].status is ApprovalStatus.PENDING


def test_content_block_preserves_raw_malformed_tool_args() -> None:
    block = ContentBlock(
        type="tool_use",
        tool_use_id="tc-bad",
        name="write",
        raw_input="{bad json",
        args_status=ToolArgsStatus.INVALID,
        args_error="unexpected character",
    )
    assert block.input is None
    assert block.raw_input == "{bad json"
    with pytest.raises(ValueError, match="bounded raw_input"):
        ContentBlock(type="tool_use", tool_use_id="tc", args_status=ToolArgsStatus.INVALID)
    with pytest.raises(ValueError, match="valid ContentBlock.input"):
        ContentBlock(type="tool_use", tool_use_id="tc", args_status=ToolArgsStatus.VALID)


def test_tool_call_carries_lifecycle_audit_metadata() -> None:
    call = ToolCall(
        tool_call_id="tc-1",
        turn=2,
        name="write",
        args={"file_path": "notes.md"},
        status=ToolCallStatus.AWAITING_APPROVAL,
        args_status=ToolArgsStatus.VALID,
        approval_request_id="apr-1",
        permission_reason="write without OS fence requires confirmation",
        permission_decided_by="user",
        permission_warnings=("job object does not fence writes",),
        capability="write",
        risk="medium",
        timeout_s=30.0,
        sandbox_backend="job",
        confinement="partial",
        env_scrubbed=("OPENAI_API_KEY",),
        artifact_refs=("artifact://sha",),
    )
    assert call.status is ToolCallStatus.AWAITING_APPROVAL
    assert call.permission_warnings == ("job object does not fence writes",)
    assert call.env_scrubbed == ("OPENAI_API_KEY",)


def test_p2_approval_and_lifecycle_commands_carry_identity() -> None:
    now = datetime.now(UTC)
    request = RequestApproval(
        run_id="run",
        tool_call_id="tc",
        request_id="apr",
        args_summary="remove files",
        risk="high",
        reason="destructive",
        expires_at=now,
    )
    resolve = ResolveApproval(run_id="run", request_id="apr", decision="allow", decided_by="user")
    expire = ExpireApproval(run_id="run", request_id="apr")
    validated = MarkToolValidated(run_id="run", tool_call_id="tc")
    running = MarkToolRunning(run_id="run", tool_call_id="tc", capability="exec", risk="high", timeout_s=30)
    mode = SetPermissionMode(run_id="run", mode="plan", changed_by="user")
    assert (request.type, resolve.type, expire.type) == ("request_approval", "resolve_approval", "expire_approval")
    assert (validated.type, running.type, mode.type) == ("mark_tool_validated", "mark_tool_running", "set_permission_mode")
    assert {EventType.APPROVAL_RESOLVED, EventType.PERMISSION_MODE_CHANGED} == {"approval_resolved", "permission_mode_changed"}
    with pytest.raises(ValueError, match="timezone-aware"):
        RequestApproval(
            run_id="run",
            tool_call_id="tc",
            request_id="apr",
            args_summary="x",
            risk="low",
            reason="test",
            expires_at=datetime(2026, 1, 1),
        )
