"""ToolCall lifecycle reduce 不变式（T4/T13 基础）。"""

from __future__ import annotations

from questor.contracts.events import Cancel, MarkToolDenied, MarkToolValidated, RecordToolResult
from questor.contracts.state_schema import Budget, CancelReason, ToolCall, ToolCallStatus
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
