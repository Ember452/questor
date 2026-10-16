"""ToolCall lifecycle reduce 不变式（T4/T13 基础）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from questor.contracts.events import (
    Cancel,
    ExpireApproval,
    MarkToolDenied,
    MarkToolRunning,
    MarkToolValidated,
    RecordToolResult,
    RequestApproval,
    ResolveApproval,
    SetPermissionMode,
)
from questor.contracts.state_schema import ApprovalStatus, Budget, CancelReason, ToolCall, ToolCallStatus
from questor.state.domain_state import Run, ToolLedger
from questor.state.reduce import reduce


def _pending_run() -> Run:
    call = ToolCall(tool_call_id="tc", turn=1, name="read", args={})
    return Run(run_id="r", budget=Budget(), tool_ledger=ToolLedger((call,)))


def test_validated_record_result_sequence() -> None:
    run = _pending_run()
    validated, events = reduce(run, MarkToolValidated(run_id="r", tool_call_id="tc"))
    assert validated.tool_ledger.calls[0].status is ToolCallStatus.VALIDATED
    assert events == []

    completed, events = reduce(validated, RecordToolResult(run_id="r", tool_call_id="tc", status="success", result="done"))
    assert completed.tool_ledger.calls[0].status is ToolCallStatus.SUCCESS
    assert [event.type for event in events] == ["tool_completed"]


def test_validated_call_can_be_denied_and_cancel_backfilled() -> None:
    run = _pending_run()
    validated, _ = reduce(run, MarkToolValidated(run_id="r", tool_call_id="tc"))
    denied, _ = reduce(validated, MarkToolDenied(run_id="r", tool_call_id="tc", reason="policy deny"))
    assert denied.tool_ledger.calls[0].status is ToolCallStatus.DENIED

    cancelled_run = _pending_run()
    cancelled_validated, _ = reduce(cancelled_run, MarkToolValidated(run_id="r", tool_call_id="tc"))
    cancelled, events = reduce(cancelled_validated, Cancel(run_id="r", reason=CancelReason.USER))
    assert cancelled.tool_ledger.calls[0].status is ToolCallStatus.CANCELLED
    assert [event.type for event in events] == ["tool_completed", "run_cancelled"]


def _validated_run() -> Run:
    run = _pending_run()
    validated, _ = reduce(run, MarkToolValidated(run_id="r", tool_call_id="tc"))
    return validated


def _request() -> RequestApproval:
    return RequestApproval(
        run_id="r",
        tool_call_id="tc",
        request_id="apr",
        args_summary="write file",
        risk="medium",
        reason="no write fence",
        expires_at=datetime.now(UTC) + timedelta(seconds=300),
    )


def test_request_and_resolve_approval_lifecycle() -> None:
    run = _validated_run()
    requested, events = reduce(run, _request())
    assert requested.status.value == "awaiting_approval"
    assert requested.tool_ledger.calls[0].status is ToolCallStatus.AWAITING_APPROVAL
    assert requested.permission_ctx.approvals[0].request_id == "apr"
    assert [event.type for event in events] == ["approval_request"]

    resolved, events = reduce(requested, ResolveApproval(run_id="r", request_id="apr", decision="allow", decided_by="user"))
    assert resolved.tool_ledger.calls[0].status is ToolCallStatus.READY
    assert resolved.permission_ctx.approvals[0].status is ApprovalStatus.APPROVED
    assert [event.type for event in events] == ["approval_resolved"]

    started, events = reduce(resolved, MarkToolRunning(run_id="r", tool_call_id="tc", capability="write", risk="medium", timeout_s=30))
    assert started.tool_ledger.calls[0].status is ToolCallStatus.RUNNING
    assert started.tool_ledger.calls[0].capability == "write"
    assert [event.type for event in events] == ["tool_started"]


def test_duplicate_opposite_expired_and_cancelled_approval_transitions_are_idempotent() -> None:
    run = _validated_run()
    requested, _ = reduce(run, _request())
    first, events = reduce(requested, ResolveApproval(run_id="r", request_id="apr", decision="allow", decided_by="user"))
    assert events
    duplicate, events = reduce(first, ResolveApproval(run_id="r", request_id="apr", decision="allow", decided_by="user"))
    assert duplicate == first
    assert events == []
    conflict, events = reduce(duplicate, ResolveApproval(run_id="r", request_id="apr", decision="deny", decided_by="user"))
    assert conflict == duplicate
    assert [event.type for event in events] == ["warning"]

    expired_run, _ = reduce(_validated_run(), _request())
    expired, events = reduce(expired_run, ExpireApproval(run_id="r", request_id="apr"))
    assert expired.permission_ctx.approvals[0].status is ApprovalStatus.EXPIRED
    assert expired.tool_ledger.calls[0].status is ToolCallStatus.DENIED
    assert [event.type for event in events] == ["approval_resolved", "tool_completed"]

    cancelled_run, _ = reduce(_validated_run(), _request())
    cancelled, events = reduce(cancelled_run, Cancel(run_id="r", reason=CancelReason.USER))
    assert cancelled.permission_ctx.approvals[0].status is ApprovalStatus.CANCELLED
    assert cancelled.tool_ledger.calls[0].status is ToolCallStatus.CANCELLED
    assert [event.type for event in events] == ["tool_completed", "run_cancelled"]


def test_set_permission_mode_updates_future_context_without_retroactive_decisions() -> None:
    run = _validated_run()
    changed, events = reduce(run, SetPermissionMode(run_id="r", mode="plan", changed_by="user"))
    assert changed.permission_ctx.mode == "plan"
    assert [event.type for event in events] == ["permission_mode_changed"]
    duplicate, events = reduce(changed, SetPermissionMode(run_id="r", mode="plan", changed_by="user"))
    assert duplicate == changed
    assert events == []
    assert changed.tool_ledger.calls[0].status is ToolCallStatus.VALIDATED

