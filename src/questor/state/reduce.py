"""L1 ``reduce`` — the SINGLE writer of Domain_State (design/01 §7; HARD C2/C5/C7/C13).

``reduce(run, command) -> (new_run, durable_events)``. It never mutates the
incoming ``Run``; it returns a brand-new one via ``dataclasses.replace`` (COW, so
the old snapshot stays valid for replay/branching — C2/C3, X3).

Enforced invariants (not the caller's honor system — design/01 §12):
- I1 pairing: a ``tool_use`` id must be unique, and a result may only close a
  still-open call.
- C7: ``Cancel`` sets cancelled AND backfills every open tool_call to an error.
- C13 / 02 E2: once terminal, the run is frozen — later commands are rejected
  with a ``warning`` event (first-writer-wins, exactly one terminal event).

Deltas (``text_delta``/``tool_progress``) are live-only and never go through
reduce (I3). This is the pure state machine; the turn loop (kernel) drives it.
"""

from __future__ import annotations

from dataclasses import replace

from questor.contracts.common import new_id, utc_now
from questor.contracts.events import (
    EVENT_SCHEMA_VERSION,
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Command,
    Envelope,
    EventType,
    FinalizeRun,
    MarkToolDenied,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.state_schema import (
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import Context, Run

_OPEN_CALL = {ToolCallStatus.PENDING, ToolCallStatus.RUNNING}


def _event(seq: int, run: Run, turn: int | None, etype: str, data: dict) -> Envelope:
    return Envelope(v=EVENT_SCHEMA_VERSION, seq=seq, run_id=run.run_id, type=etype, turn=turn, data=data)


def reduce(run: Run, command: Command) -> tuple[Run, list[Envelope]]:  # noqa: C901 (dispatch is a flat table)
    """Apply one Command; return the new Run + durable events (seq-ordered)."""
    if run.status.is_terminal:
        # C13 first-writer-wins: freeze after the single terminal event.
        msg = f"run {run.run_id} already {run.status}; ignored {command.type}"
        return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": msg})]

    if isinstance(command, SubmitMessage):
        was_idle = run.status is RunStatus.IDLE
        ctx = replace(run.context, items=(*run.context.items, command.content))
        new = replace(run, context=ctx, status=RunStatus.RUNNING if was_idle else run.status)
        seq = new.seq + 1
        events = [_event(seq, new, None, EventType.RUN_STARTED, {"run_id": new.run_id})] if was_idle else []
        return replace(new, seq=seq) if events else new, events

    if isinstance(command, AdvanceTurn):
        new = replace(run, turn=command.turn, seq=run.seq + 1)
        return new, [_event(new.seq, new, command.turn, EventType.TURN_STARTED, {"turn": command.turn})]

    if isinstance(command, AppendAssistantMessage):
        use_ids = [b.tool_use_id for b in command.message.content if b.type == "tool_use" and b.tool_use_id]
        known = {c.tool_call_id for c in run.tool_ledger.calls}
        if any(i in known for i in use_ids):
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": "duplicate tool_use id; command rejected"})]
        new_calls = tuple(
            ToolCall(tool_call_id=b.tool_use_id, turn=command.turn, name=b.name or "", args=dict(b.input or {}), status=ToolCallStatus.PENDING)
            for b in command.message.content
            if b.type == "tool_use" and b.tool_use_id
        )
        ledger = replace(run.tool_ledger, calls=(*run.tool_ledger.calls, *new_calls))
        ctx = replace(run.context, items=(*run.context.items, command.message))
        new = replace(run, context=ctx, tool_ledger=ledger, seq=run.seq + 1)
        return new, [_event(new.seq, new, command.turn, EventType.MESSAGE_COMPLETED, {"message_id": command.message.id})]

    if isinstance(command, RecordToolResult):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"no open tool_call {command.tool_call_id}; rejected"})]
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, replace(target, status=_call_status(command.status), result=command.result, display=command.display)))
        ctx = _append_tool_result(run.context, command.tool_call_id, command.result, is_error=command.status != "success")
        new = replace(run, tool_ledger=ledger, context=ctx, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_COMPLETED, {"tool_call_id": command.tool_call_id, "status": command.status})]

    if isinstance(command, MarkToolDenied):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"no open tool_call to deny {command.tool_call_id}"})]
        denied = replace(target, status=ToolCallStatus.DENIED, permission_decision="deny", result=command.reason)
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, denied))
        ctx = _append_tool_result(run.context, command.tool_call_id, f"denied: {command.reason}", is_error=True)
        new = replace(run, tool_ledger=ledger, context=ctx, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_COMPLETED, {"tool_call_id": command.tool_call_id, "status": "denied"})]

    if isinstance(command, Cancel):
        open_calls = _open_calls(run)
        closed, extra = _backfill_open_calls(run)
        ledger = replace(run.tool_ledger, calls=closed)
        ctx = replace(run.context, items=extra)
        # Allocate contiguous seqs for all emitted events (backfill + the single
        # terminal), then advance Run.seq to the last one — never reuse a seq
        # (ADR-0011; the old run.seq+1 / new.seq collision broke store.append).
        seq = run.seq
        events: list[Envelope] = []
        for call in open_calls:
            seq += 1
            events.append(_event(seq, run, None, EventType.TOOL_COMPLETED, {"tool_call_id": call.tool_call_id, "status": "cancelled"}))
        seq += 1
        events.append(_event(seq, run, run.turn, EventType.RUN_CANCELLED, {"reason": str(command.reason)}))
        new = replace(run, tool_ledger=ledger, context=ctx, status=RunStatus.CANCELLED, cancel_reason=command.reason, completed_at=utc_now(), seq=seq)
        return new, events

    if isinstance(command, FinalizeRun):
        if command.status == "failed":
            stack = (*run.error_stack, command.error) if command.error else run.error_stack
            new = replace(run, status=RunStatus.FAILED, error_stack=stack, completed_at=utc_now(), seq=run.seq + 1)
            err = {"code": command.error.kind.value, "message": command.error.message, "retryable": command.error.hints.retryable} if command.error else {}
            return new, [_event(new.seq, new, new.turn, EventType.RUN_FAILED, {"error": err})]
        items = (*run.context.items, command.final) if command.final is not None else run.context.items
        new = replace(run, context=replace(run.context, items=items), status=RunStatus.COMPLETED, completed_at=utc_now(), seq=run.seq + 1)
        return new, [_event(new.seq, new, new.turn, EventType.RUN_COMPLETED, {"usage": command.usage or {}, "exit_reason": command.exit_reason})]

    # Unhandled command => reject with a warning (never crash the loop, design/04 L1).
    return run, [
        _event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"unsupported command {command.type}"})
    ]


def _open_calls(run: Run) -> tuple[ToolCall, ...]:
    return tuple(c for c in run.tool_ledger.calls if c.status in _OPEN_CALL)


def _open_call(run: Run, tool_call_id: str) -> ToolCall | None:
    return next((c for c in _open_calls(run) if c.tool_call_id == tool_call_id), None)


def _call_status(status: str) -> ToolCallStatus:
    mapping = {
        "success": ToolCallStatus.SUCCESS,
        "error": ToolCallStatus.ERROR,
        "critical_error": ToolCallStatus.CRITICAL_ERROR,
    }
    return mapping.get(status, ToolCallStatus.ERROR)


def _replace_call(calls: tuple[ToolCall, ...], updated: ToolCall) -> tuple[ToolCall, ...]:
    return tuple(updated if c.tool_call_id == updated.tool_call_id else c for c in calls)


def _append_tool_result(ctx: Context, tool_call_id: str, result: object, *, is_error: bool) -> Context:
    block = ContentBlock(type="tool_result", tool_use_id=tool_call_id, text=str(result), is_error=is_error)
    msg = Message(id=new_id("msg"), role=Role.TOOL, content=(block,), seq=len(ctx.items))
    return replace(ctx, items=(*ctx.items, msg))


def _backfill_open_calls(run: Run) -> tuple[tuple[ToolCall, ...], tuple[Message, ...]]:
    """C7: close every open call with an error result; keep pairing intact."""
    closed = tuple(
        replace(c, status=ToolCallStatus.ERROR, result="cancelled before completion")
        for c in run.tool_ledger.calls
    )
    extra = tuple(
        Message(
            id=new_id("msg"),
            role=Role.TOOL,
            content=(ContentBlock(type="tool_result", tool_use_id=c.tool_call_id, text="cancelled", is_error=True),),
            seq=len(run.context.items) + i,
        )
        for i, c in enumerate(_open_calls(run))
    )
    return closed, extra
