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
    FinalizeRun,
    MarkToolDenied,
    MarkToolValidated,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import Context, Run

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

    if isinstance(command, Cancel):
        open_calls = _open_calls(run)
        closed, extra = _backfill_open_calls(run)
        ledger = replace(run.tool_ledger, calls=closed)
        ctx = replace(run.context, items=extra)
        # 为本次产出的全部事件（回填 + 唯一终态）连续取号，再把 Run.seq 推进到最后一个号——
        # 绝不复用同一 seq（ADR-0011；旧写法 run.seq+1 与 new.seq 相撞会打断 store.append）。
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

    # 未处理的 Command → 以 warning 拒绝（绝不崩循环，design/04 L1）。
    return run, [
        _event(run.seq + 1, run, run.turn, EventType.WARNING, {"message": f"unsupported command {command.type}"})
    ]


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


def _backfill_open_calls(run: Run) -> tuple[tuple[ToolCall, ...], tuple[Message, ...]]:
    """C7：用 cancelled 结果闭合每一个未完成的调用，保住配对不变式。

    取消不是普通工具 error：账本必须保留可区分事实，resume/审计才能判断进程被用户停止
    而非业务失败（ADR-0016）。
    """
    open_ids = {c.tool_call_id for c in _open_calls(run)}
    closed = tuple(
        replace(c, status=ToolCallStatus.CANCELLED, result="cancelled before completion")
        if c.tool_call_id in open_ids
        else c
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
