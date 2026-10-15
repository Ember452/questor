"""L1 Run <-> 普通 dict 快照（checkpoint 的序列化/反序列化）。

供 turn 边界的 checkpoint 与 ``resume`` 使用：把权威的 ``Run`` 序列化成 JSON 安全的
dict，或从其重建（ADR-0005：恢复 = 最近快照 + 其后事件重放；P1 以 turn 边界快照作为
还原点）。JSON 叶是 ``immutables`` Map 的 thaw，从而可被序列化。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from questor.contracts.common import freeze, thaw
from questor.contracts.state_schema import (
    Budget,
    CancelReason,
    Checkpoint,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import Context, DomainState, PermissionCtx, Run, SessionDefaults, TaskTree, ToolLedger  # noqa: F401  （标注形状，供阅读）


def _block_to(b: ContentBlock) -> dict[str, Any]:
    """ContentBlock → dict（Map 叶经 thaw 还原为普通 dict）。"""
    return {
        "type": b.type,
        "text": b.text,
        "tool_use_id": b.tool_use_id,
        "name": b.name,
        "input": thaw(b.input) if b.input is not None else None,
        "is_error": b.is_error,
        "payload": thaw(b.payload) if b.payload is not None else None,
        "provider_state": thaw(b.provider_state) if b.provider_state is not None else None,
    }


def _block_from(d: dict[str, Any]) -> ContentBlock:
    """dict → ContentBlock（构造期会再次深冻结）。"""
    return ContentBlock(
        type=d["type"],
        text=d.get("text"),
        tool_use_id=d.get("tool_use_id"),
        name=d.get("name"),
        input=d.get("input"),
        is_error=d.get("is_error"),
        payload=d.get("payload"),
        provider_state=d.get("provider_state"),
    )


def _msg_to(m: Message) -> dict[str, Any]:
    """Message → dict；时间戳转 ISO 字符串以便 JSON 化。"""
    return {"id": m.id, "role": m.role.value, "seq": m.seq, "created_at": m.created_at.isoformat(), "content": [_block_to(b) for b in m.content]}


def _msg_from(d: dict[str, Any]) -> Message:
    """dict → Message；字符串角色/时间戳还原为枚举与 tz-aware datetime。"""
    return Message(
        id=d["id"],
        role=Role(d["role"]),
        seq=d["seq"],
        created_at=datetime.fromisoformat(d["created_at"]),
        content=tuple(_block_from(b) for b in d["content"]),
    )


def _call_to(c: ToolCall) -> dict[str, Any]:
    """ToolCall → dict（args/result 经 thaw 还原）。"""
    return {
        "tool_call_id": c.tool_call_id,
        "turn": c.turn,
        "name": c.name,
        "args": thaw(c.args),
        "status": c.status.value,
        "result": thaw(c.result) if isinstance(c.result, (dict, list, tuple)) else c.result,
        "permission_decision": c.permission_decision,
    }


def _call_from(d: dict[str, Any]) -> ToolCall:
    """dict → ToolCall；result 为容器时再次深冻结以保持不可变。"""
    return ToolCall(
        tool_call_id=d["tool_call_id"],
        turn=d["turn"],
        name=d["name"],
        args=d.get("args") or {},
        status=ToolCallStatus(d.get("status", "pending")),
        result=freeze(d["result"]) if isinstance(d.get("result"), (dict, list, tuple)) else d.get("result"),
        permission_decision=d.get("permission_decision"),
    )


def to_snapshot(run: Run) -> dict[str, Any]:
    """把 Run 序列化为 JSON 安全的 dict（不可变叶已 thaw）。"""
    return {
        "run_id": run.run_id,
        "seq": run.seq,
        "turn": run.turn,
        "status": run.status.value,
        "cancel_reason": run.cancel_reason.value if run.cancel_reason else None,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "budget": {
            "max_turns": run.budget.max_turns,
            "max_tokens": run.budget.max_tokens,
            "deadline_seconds": run.budget.deadline_seconds,
            "repeat_tool_limit": run.budget.repeat_tool_limit,
            "max_consecutive_continuations": run.budget.max_consecutive_continuations,
        },
        "items": [_msg_to(m) for m in run.context.items],
        "calls": [_call_to(c) for c in run.tool_ledger.calls],
        "checkpoints": [
            {"cp_id": cp.cp_id, "seq": cp.seq, "turn": cp.turn, "kind": cp.kind, "state_digest": cp.state_digest, "pending": list(cp.pending_tool_calls)}
            for cp in run.checkpoints
        ],
    }


def from_snapshot(d: dict[str, Any]) -> Run:
    """从 :func:`to_snapshot` 的输出重建 Run。"""
    b = d.get("budget", {})
    ctx = Context(items=tuple(_msg_from(m) for m in d.get("items", [])))
    ledger = ToolLedger(calls=tuple(_call_from(c) for c in d.get("calls", [])))
    checkpoints = tuple(
        Checkpoint(cp_id=c["cp_id"], seq=c["seq"], turn=c["turn"], kind=c["kind"], state_digest=c["state_digest"], pending_tool_calls=tuple(c.get("pending", ())))
        for c in d.get("checkpoints", [])
    )
    return Run(
        run_id=d["run_id"],
        seq=d["seq"],
        turn=d["turn"],
        status=RunStatus(d["status"]),
        budget=Budget(**b) if b else Budget(),
        context=ctx,
        tool_ledger=ledger,
        checkpoints=checkpoints,
        permission_ctx=PermissionCtx(),
        cancel_reason=CancelReason(d["cancel_reason"]) if d.get("cancel_reason") else None,
        created_at=datetime.fromisoformat(d["created_at"]),
        completed_at=datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None,
    )


__all__ = ["to_snapshot", "from_snapshot", "DomainState", "SessionDefaults"]
