"""L1 ``reduce`` —— Domain_State 的**唯一写者**（design/01 §7；HARD C2/C5/C7/C13）。

``reduce(run, command) -> (new_run, durable_events)``。它绝不原地改传入的 ``Run``，
而是经 ``dataclasses.replace`` 返回一个全新的（COW，旧快照对回放/分支仍有效——C2/C3、X3）。

在 reduce 内部强制的不变式（不靠上层自觉，design/01 §12）：
- I1 配对：``tool_use`` id 必须唯一，且结果只能闭合一个仍打开的调用。
- C7：``Cancel`` 置 cancelled **且**把所有未闭合 tool_call 回填为 error。
- C13 / 02 E2：一旦终态即冻结——后续 Command 被拒并发 ``warning`` 事件（first-writer-wins，恰一终态）。

delta（``text_delta``/``tool_progress``）是 live-only、绝不经 reduce（I3）。这是纯状态机；
turn 循环（kernel）驱动它。
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
    ExpireApproval,
    FinalizeRun,
    MarkToolDenied,
    MarkToolRunning,
    MarkToolValidated,
    RecordToolResult,
    RequestApproval,
    ResolveApproval,
    SetPermissionMode,
    SubmitMessage,
)
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import Context, PermissionCtx, PermissionDecisionRecord, Run

_OPEN_CALL = OPEN_TOOL_CALL_STATUSES


def _event(seq: int, run: Run, turn: int | None, etype: str, data: dict) -> Envelope:
    """构造一个对外事件信封（v 取 wire 版本，run_id 取自当前 run）。"""
    return Envelope(v=EVENT_SCHEMA_VERSION, seq=seq, run_id=run.run_id, type=etype, turn=turn, data=data)


def reduce(run: Run, command: Command) -> tuple[Run, list[Envelope]]:  # noqa: C901
    """应用一条 Command；返回新 Run + 按 seq 有序的可持久事件。"""
    if run.status.is_terminal:
        # C13 first-writer-wins：终态后冻结，忽略后续写。
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
            ToolCall(
                tool_call_id=b.tool_use_id,
                turn=command.turn,
                name=b.name or "",
                args=dict(b.input or {}),
                args_status=b.args_status,
                raw_args_summary=b.raw_input,
                permission_reason=b.args_error,
                status=ToolCallStatus.PENDING,
            )
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

    if isinstance(command, MarkToolValidated):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            # 已 validated/闭合的重复 transition 是幂等 no-op；未知 id 同样不产 durable event，
            # 避免把内部 lifecycle 噪声污染 replay。
            return run, []
        if target.status is ToolCallStatus.VALIDATED:
            return run, []
        validated = replace(target, status=ToolCallStatus.VALIDATED)
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, validated))
        return replace(run, tool_ledger=ledger), []

    if isinstance(command, MarkToolDenied):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"no open tool_call to deny {command.tool_call_id}"})]
        denied = replace(target, status=ToolCallStatus.DENIED, permission_decision="deny", result=command.reason)
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, denied))
        ctx = _append_tool_result(run.context, command.tool_call_id, f"denied: {command.reason}", is_error=True)
        new = replace(run, tool_ledger=ledger, context=ctx, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_COMPLETED, {"tool_call_id": command.tool_call_id, "status": "denied"})]

    if isinstance(command, RequestApproval):
        target = _open_call(run, command.tool_call_id)
        existing = next((a for a in run.permission_ctx.approvals if a.request_id == command.request_id), None)
        if existing is not None:
            if existing.status is ApprovalStatus.PENDING and existing.tool_call_id == command.tool_call_id:
                return run, []
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"approval request {command.request_id} conflicts with an existing request"})]
        if target is None:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"no open tool_call to approve {command.tool_call_id}"})]
        requested = replace(
            target,
            status=ToolCallStatus.AWAITING_APPROVAL,
            approval_request_id=command.request_id,
            permission_reason=command.reason,
        )
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, requested))
        request = ApprovalRequest(
            request_id=command.request_id,
            tool_call_id=command.tool_call_id,
            args_summary=command.args_summary,
            risk=command.risk,
            reason=command.reason,
            created_at=utc_now(),
            expires_at=command.expires_at,
        )
        permissions = replace(run.permission_ctx, approvals=(*run.permission_ctx.approvals, request))
        new = replace(run, tool_ledger=ledger, permission_ctx=permissions, status=RunStatus.AWAITING_APPROVAL, seq=run.seq + 1)
        event_data = {
            "request_id": request.request_id,
            "tool_call_id": command.tool_call_id,
            "name": target.name,
            "args_summary": command.args_summary,
            "risk": command.risk,
            "reason": command.reason,
            "expires_at": command.expires_at.isoformat(),
        }
        return new, [_event(new.seq, new, target.turn, EventType.APPROVAL_REQUEST, event_data)]

    if isinstance(command, ResolveApproval):
        return _resolve_approval(run, command, decision=command.decision, decided_by=command.decided_by, status=ApprovalStatus.APPROVED if command.decision == "allow" else ApprovalStatus.DENIED, expired=False)

    if isinstance(command, ExpireApproval):
        return _resolve_approval(run, command, decision="deny", decided_by="timeout", status=ApprovalStatus.EXPIRED, expired=True)

    if isinstance(command, SetPermissionMode):
        if command.mode not in {"default", "plan", "full_auto"}:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"invalid permission mode {command.mode}"})]
        if run.permission_ctx.mode == command.mode:
            return run, []
        permissions = replace(run.permission_ctx, mode=command.mode)
        new = replace(run, permission_ctx=permissions, seq=run.seq + 1)
        return new, [_event(new.seq, new, run.turn, EventType.PERMISSION_MODE_CHANGED, {"mode": command.mode, "changed_by": command.changed_by, "effective_from_turn": run.turn + 1})]

    if isinstance(command, MarkToolRunning):
        target = _open_call(run, command.tool_call_id)
        if target is None:
            return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"no open tool_call to start {command.tool_call_id}"})]
        if target.status is ToolCallStatus.RUNNING:
            return run, []
        started = replace(
            target,
            status=ToolCallStatus.RUNNING,
            capability=command.capability,
            risk=command.risk,
            timeout_s=command.timeout_s,
            started_at=utc_now(),
        )
        ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, started))
        new = replace(run, tool_ledger=ledger, status=RunStatus.RUNNING, seq=run.seq + 1)
        return new, [_event(new.seq, new, target.turn, EventType.TOOL_STARTED, {
            "tool_call_id": command.tool_call_id,
            "name": target.name,
            "capability": command.capability,
            "risk": command.risk,
            "args_summary": target.raw_args_summary or target.name,
        })]

    if isinstance(command, Cancel):
        open_calls = _open_calls(run)
        closed, extra = _backfill_open_calls(run)
        ledger = replace(run.tool_ledger, calls=closed)
        ctx = replace(run.context, items=extra)
        permissions = _cancel_pending_approvals(run.permission_ctx)
        # 为本次产出的全部事件（回填 + 唯一终态）连续取号，再把 Run.seq 推进到最后一个号——
        # 绝不复用同一 seq（ADR-0011；旧写法 run.seq+1 与 new.seq 相撞会打断 store.append）。
        seq = run.seq
        events: list[Envelope] = []
        for call in open_calls:
            seq += 1
            events.append(_event(seq, run, None, EventType.TOOL_COMPLETED, {"tool_call_id": call.tool_call_id, "status": "cancelled"}))
        seq += 1
        events.append(_event(seq, run, run.turn, EventType.RUN_CANCELLED, {"reason": str(command.reason)}))
        new = replace(run, tool_ledger=ledger, context=ctx, permission_ctx=permissions, status=RunStatus.CANCELLED, cancel_reason=command.reason, completed_at=utc_now(), seq=seq)
        return new, events

    if isinstance(command, FinalizeRun):
        # 任何终态都必须先闭合还开着的 tool_use（C7/I1）。failed 分支以前直接落终态，
        # 把未配对的 tool_use 留在 context；P3 做 resume/after_seq 续传时会被原样喂回 provider
        # （Anthropic/OpenAI 强制 tool_use↔tool_result 成对，直接 4xx），所以在这一步就补上。
        open_calls = _open_calls(run)
        closed, extra_messages = _backfill_open_calls(run, note=f"run finished as {command.status} before this call completed")
        ledger = replace(run.tool_ledger, calls=closed)
        items = (*run.context.items, *extra_messages)
        seq = run.seq
        events: list[Envelope] = []
        for call in open_calls:
            seq += 1
            events.append(_event(seq, run, None, EventType.TOOL_COMPLETED, {"tool_call_id": call.tool_call_id, "status": "cancelled"}))
        if command.status == "failed":
            stack = (*run.error_stack, command.error) if command.error else run.error_stack
            err = {"code": command.error.kind.value, "message": command.error.message, "retryable": command.error.hints.retryable} if command.error else {}
            seq += 1
            events.append(_event(seq, run, run.turn, EventType.RUN_FAILED, {"error": err}))
            new = replace(
                run,
                tool_ledger=ledger,
                context=replace(run.context, items=items),
                status=RunStatus.FAILED,
                error_stack=stack,
                completed_at=utc_now(),
                seq=seq,
            )
            return new, events
        if command.final is not None:
            items = (*items, command.final)
        seq += 1
        events.append(_event(seq, run, run.turn, EventType.RUN_COMPLETED, {"usage": command.usage or {}, "exit_reason": command.exit_reason}))
        new = replace(
            run,
            tool_ledger=ledger,
            context=replace(run.context, items=items),
            status=RunStatus.COMPLETED,
            completed_at=utc_now(),
            seq=seq,
        )
        return new, events

    # 未处理的 Command → 以 warning 拒绝（绝不崩循环，design/04 L1）。
    return run, [
        _event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"unsupported command {command.type}"})
    ]


def _cancel_pending_approvals(ctx: PermissionCtx) -> PermissionCtx:
    return replace(
        ctx,
        approvals=tuple(
            replace(a, status=ApprovalStatus.CANCELLED, decision="deny", decided_by="cancel", resolved_at=utc_now()) if a.status is ApprovalStatus.PENDING else a
            for a in ctx.approvals
        ),
    )


def _resolve_approval(
    run: Run,
    command: object,
    *,
    decision: str,
    decided_by: str,
    status: ApprovalStatus,
    expired: bool,
) -> tuple[Run, list[Envelope]]:
    request_id = command.request_id
    tool_call_id = getattr(command, "tool_call_id", None)
    approval = next((item for item in run.permission_ctx.approvals if item.request_id == request_id), None)
    if approval is None or (tool_call_id is not None and approval.tool_call_id != tool_call_id):
        return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"unknown approval request {request_id}"})]
    if approval.status is not ApprovalStatus.PENDING:
        if approval.decision == decision:
            return run, []
        return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"approval {request_id} already {approval.status.value}"})]
    now = utc_now()
    target = _open_call(run, approval.tool_call_id)
    if target is None:
        return run, [_event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"approval {request_id} has no open tool_call"})]
    resolved = replace(approval, status=status, decision=decision, decided_by=decided_by, resolved_at=now)
    permissions = replace(
        run.permission_ctx,
        approvals=tuple(resolved if a.request_id == request_id else a for a in run.permission_ctx.approvals),
        decisions=(*run.permission_ctx.decisions, PermissionDecisionRecord(tool_call_id=target.tool_call_id, decision=decision, decided_by=decided_by, at=now, request_id=request_id)),
    )
    if decision == "allow":
        call = replace(target, status=ToolCallStatus.READY, permission_decision="allow", permission_reason=approval.reason, permission_decided_by=decided_by)
        ctx = run.context
        run_status = RunStatus.RUNNING
    else:
        reason = "approval expired before a decision" if expired else f"approval denied: {approval.reason}"
        call = replace(target, status=ToolCallStatus.DENIED, permission_decision="deny", permission_reason=reason, permission_decided_by=decided_by, result=reason, ended_at=now)
        ctx = _append_tool_result(run.context, target.tool_call_id, reason, is_error=True)
        run_status = RunStatus.RUNNING
    ledger = replace(run.tool_ledger, calls=_replace_call(run.tool_ledger.calls, call))
    seq = run.seq
    events: list[Envelope] = []
    seq += 1
    events.append(_event(seq, run, target.turn, EventType.APPROVAL_RESOLVED, {
        "request_id": request_id,
        "tool_call_id": target.tool_call_id,
        "decision": decision,
        "decided_by": decided_by,
        "resolved_at": now.isoformat(),
    }))
    if decision != "allow":
        seq += 1
        events.append(_event(seq, run, target.turn, EventType.TOOL_COMPLETED, {"tool_call_id": target.tool_call_id, "status": "denied"}))
    return replace(run, tool_ledger=ledger, context=ctx, permission_ctx=permissions, status=run_status, seq=seq), events


def _open_calls(run: Run) -> tuple[ToolCall, ...]:
    """返回仍打开（pending/running）的调用。"""
    return tuple(c for c in run.tool_ledger.calls if c.status in _OPEN_CALL)


def _open_call(run: Run, tool_call_id: str) -> ToolCall | None:
    """按 id 找一个仍打开的调用；找不到（已闭合/不存在）返回 None。"""
    return next((c for c in _open_calls(run) if c.tool_call_id == tool_call_id), None)


def _call_status(status: str) -> ToolCallStatus:
    """把工具返回的字符串状态映射为账本枚举；未知一律按 error（fail-closed）。"""
    mapping = {
        "success": ToolCallStatus.SUCCESS,
        "error": ToolCallStatus.ERROR,
        "critical_error": ToolCallStatus.CRITICAL_ERROR,
        "timed_out": ToolCallStatus.TIMED_OUT,
        "cancelled": ToolCallStatus.CANCELLED,
    }
    return mapping.get(status, ToolCallStatus.ERROR)


def _replace_call(calls: tuple[ToolCall, ...], updated: ToolCall) -> tuple[ToolCall, ...]:
    """不可变替换：返回把匹配 id 的那条换成 ``updated`` 的新元组。"""
    return tuple(updated if c.tool_call_id == updated.tool_call_id else c for c in calls)


def _append_tool_result(ctx: Context, tool_call_id: str, result: object, *, is_error: bool) -> Context:
    """追加一条含 tool_result 的消息，维持 tool_use↔tool_result 配对（I1）。"""
    block = ContentBlock(type="tool_result", tool_use_id=tool_call_id, text=str(result), is_error=is_error)
    msg = Message(id=new_id("msg"), role=Role.TOOL, content=(block,), seq=len(ctx.items))
    return replace(ctx, items=(*ctx.items, msg))


def _backfill_open_calls(run: Run, *, note: str = "cancelled before completion") -> tuple[tuple[ToolCall, ...], tuple[Message, ...]]:
    """C7：用 cancelled 结果闭合每一个未完成的调用，保住配对不变式。

    取消不是普通工具 error：账本必须保留可区分事实，resume/审计才能判断进程被用户停止
    而非业务失败（ADR-0016）。`note` 区分两种成因：用户取消 vs 落终态时尚未完成；
    两者都是 cancelled 状态，但后者额外带运行终态说明，供回放与审计区分。
    """
    open_ids = {c.tool_call_id for c in _open_calls(run)}
    closed = tuple(
        replace(c, status=ToolCallStatus.CANCELLED, result=note)
        if c.tool_call_id in open_ids
        else c
        for c in run.tool_ledger.calls
    )
    extra = tuple(
        Message(
            id=new_id("msg"),
            role=Role.TOOL,
            content=(ContentBlock(type="tool_result", tool_use_id=c.tool_call_id, text=note, is_error=True),),
            seq=len(run.context.items) + i,
        )
        for i, c in enumerate(_open_calls(run))
    )
    return closed, extra
