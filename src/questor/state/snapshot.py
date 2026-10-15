"""L1 Run <-> 普通 dict 快照（checkpoint 的序列化/反序列化）。

v2 起快照必须携带完整权威状态：task_tree、permission_ctx、approval requests、ToolCall
生命周期字段、error_stack 与 context 压缩边界。不能再用默认 PermissionCtx 静默吞掉权限决策
（ADR-0014/0016/0019）。

JSON 叶是 ``immutables`` Map 的 thaw，从而可被序列化；未知版本 fail-closed，不猜测语义。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from questor.contracts.common import freeze, thaw, utc_now
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.state_schema import (
    ApprovalRequest,
    ApprovalStatus,
    Budget,
    CancelReason,
    Checkpoint,
    ContentBlock,
    Message,
    PermissionRule,
    Role,
    RunStatus,
    TaskKind,
    TaskNode,
    TaskStatus,
    ToolArgsStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.state.domain_state import (
    Context,
    DomainState,
    PermissionCtx,
    PermissionDecisionRecord,
    Run,
    TaskTree,
    ToolLedger,
)

SNAPSHOT_VERSION = 2
_MIN_SUPPORTED_VERSION = 1


class SnapshotVersionError(ValueError):
    """快照 schema 版本未知或过新；恢复必须显式失败，不能半重建。"""


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _block_to(b: ContentBlock) -> dict[str, Any]:
    return {
        "type": b.type,
        "text": b.text,
        "tool_use_id": b.tool_use_id,
        "name": b.name,
        "input": thaw(b.input) if b.input is not None else None,
        "is_error": b.is_error,
        "payload": thaw(b.payload) if b.payload is not None else None,
        "provider_state": thaw(b.provider_state) if b.provider_state is not None else None,
        "raw_input": b.raw_input,
        "args_status": b.args_status.value,
        "args_error": b.args_error,
    }


def _block_from(d: dict[str, Any]) -> ContentBlock:
    return ContentBlock(
        type=d["type"],
        text=d.get("text"),
        tool_use_id=d.get("tool_use_id"),
        name=d.get("name"),
        input=d.get("input"),
        is_error=d.get("is_error"),
        payload=d.get("payload"),
        provider_state=d.get("provider_state"),
        raw_input=d.get("raw_input"),
        args_status=ToolArgsStatus(d.get("args_status", ToolArgsStatus.MISSING.value)),
        args_error=d.get("args_error"),
    )


def _msg_to(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role.value,
        "seq": m.seq,
        "created_at": m.created_at.isoformat(),
        "content": [_block_to(b) for b in m.content],
    }


def _msg_from(d: dict[str, Any]) -> Message:
    return Message(
        id=d["id"],
        role=Role(d["role"]),
        seq=d["seq"],
        created_at=datetime.fromisoformat(d["created_at"]),
        content=tuple(_block_from(b) for b in d["content"]),
    )


def _call_to(c: ToolCall) -> dict[str, Any]:
    return {
        "tool_call_id": c.tool_call_id,
        "turn": c.turn,
        "name": c.name,
        "args": thaw(c.args),
        "status": c.status.value,
        "result": thaw(c.result) if isinstance(c.result, (dict, list, tuple)) else c.result,
        "display": thaw(c.display) if isinstance(c.display, (dict, list, tuple)) else c.display,
        "permission_decision": c.permission_decision,
        "args_status": c.args_status.value,
        "raw_args_summary": c.raw_args_summary,
        "approval_request_id": c.approval_request_id,
        "permission_reason": c.permission_reason,
        "permission_decided_by": c.permission_decided_by,
        "permission_warnings": list(c.permission_warnings),
        "capability": c.capability,
        "risk": c.risk,
        "timeout_s": c.timeout_s,
        "sandbox_backend": c.sandbox_backend,
        "confinement": c.confinement,
        "env_scrubbed": list(c.env_scrubbed),
        "artifact_refs": list(c.artifact_refs),
        "node_id": c.node_id,
        "seq_request": c.seq_request,
        "seq_result": c.seq_result,
        "started_at": _dt(c.started_at),
        "ended_at": _dt(c.ended_at),
    }


def _call_from(d: dict[str, Any]) -> ToolCall:
    return ToolCall(
        tool_call_id=d["tool_call_id"],
        turn=d["turn"],
        name=d["name"],
        args=d.get("args") or {},
        status=ToolCallStatus(d.get("status", ToolCallStatus.PENDING.value)),
        result=freeze(d["result"]) if isinstance(d.get("result"), (dict, list, tuple)) else d.get("result"),
        display=freeze(d["display"]) if isinstance(d.get("display"), (dict, list, tuple)) else d.get("display"),
        permission_decision=d.get("permission_decision"),
        args_status=ToolArgsStatus(d.get("args_status", ToolArgsStatus.MISSING.value)),
        raw_args_summary=d.get("raw_args_summary"),
        approval_request_id=d.get("approval_request_id"),
        permission_reason=d.get("permission_reason"),
        permission_decided_by=d.get("permission_decided_by"),
        permission_warnings=tuple(d.get("permission_warnings", ())),
        capability=d.get("capability"),
        risk=d.get("risk"),
        timeout_s=d.get("timeout_s"),
        sandbox_backend=d.get("sandbox_backend"),
        confinement=d.get("confinement"),
        env_scrubbed=tuple(d.get("env_scrubbed", ())),
        artifact_refs=tuple(d.get("artifact_refs", ())),
        node_id=d.get("node_id"),
        seq_request=d.get("seq_request"),
        seq_result=d.get("seq_result"),
        started_at=_parse_dt(d.get("started_at")),
        ended_at=_parse_dt(d.get("ended_at")),
    )


def _node_to(n: TaskNode) -> dict[str, Any]:
    return {
        "id": n.id,
        "title": n.title,
        "objective": n.objective,
        "parent_id": n.parent_id,
        "kind": n.kind.value,
        "status": n.status.value,
        "deps": list(n.deps),
        "assigned_run_id": n.assigned_run_id,
        "result": n.result,
    }


def _node_from(d: dict[str, Any]) -> TaskNode:
    return TaskNode(
        id=d["id"],
        title=d["title"],
        objective=d.get("objective", ""),
        parent_id=d.get("parent_id"),
        kind=TaskKind(d.get("kind", TaskKind.TASK.value)),
        status=TaskStatus(d.get("status", TaskStatus.PENDING.value)),
        deps=tuple(d.get("deps", ())),
        assigned_run_id=d.get("assigned_run_id"),
        result=d.get("result"),
    )


def _rule_to(r: PermissionRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "tool_pattern": r.tool_pattern,
        "argument_pattern": r.argument_pattern,
        "action": r.action,
        "scope": r.scope,
        "created_at": _dt(r.created_at),
    }


def _rule_from(d: dict[str, Any]) -> PermissionRule:
    return PermissionRule(
        id=d["id"],
        tool_pattern=d.get("tool_pattern", d.get("permission", "*")),
        argument_pattern=d.get("argument_pattern", d.get("pattern", "*")),
        action=d["action"],
        scope=d.get("scope", "*"),
        created_at=_parse_dt(d.get("created_at")),
    )


def _decision_to(r: PermissionDecisionRecord) -> dict[str, Any]:
    return {
        "tool_call_id": r.tool_call_id,
        "decision": r.decision,
        "decided_by": r.decided_by,
        "at": _dt(r.at),
        "request_id": r.request_id,
    }


def _decision_from(d: dict[str, Any]) -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        tool_call_id=d["tool_call_id"],
        decision=d["decision"],
        decided_by=d["decided_by"],
        at=_parse_dt(d.get("at")) or utc_now(),
        request_id=d.get("request_id"),
    )


def _approval_to(a: ApprovalRequest) -> dict[str, Any]:
    return {
        "request_id": a.request_id,
        "tool_call_id": a.tool_call_id,
        "status": a.status.value,
        "args_summary": a.args_summary,
        "risk": a.risk,
        "reason": a.reason,
        "created_at": _dt(a.created_at),
        "expires_at": _dt(a.expires_at),
        "decision": a.decision,
        "decided_by": a.decided_by,
        "resolved_at": _dt(a.resolved_at),
    }


def _approval_from(d: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=d["request_id"],
        tool_call_id=d["tool_call_id"],
        status=ApprovalStatus(d.get("status", ApprovalStatus.PENDING.value)),
        args_summary=d["args_summary"],
        risk=d["risk"],
        reason=d["reason"],
        created_at=datetime.fromisoformat(d["created_at"]),
        expires_at=datetime.fromisoformat(d["expires_at"]),
        decision=d.get("decision"),
        decided_by=d.get("decided_by"),
        resolved_at=_parse_dt(d.get("resolved_at")),
    )


def _permission_to(p: PermissionCtx) -> dict[str, Any]:
    return {
        "mode": p.mode,
        "rules": [_rule_to(r) for r in p.rules],
        "denylist": sorted(p.denylist),
        "approvals": [_approval_to(a) for a in p.approvals],
        "decisions": [_decision_to(r) for r in p.decisions],
        "workspace_root": p.workspace_root,
        "cwd": p.cwd,
        "approval_policy": p.approval_policy,
        "protect_sensitive_paths": p.protect_sensitive_paths,
        "enforce_read_only": p.enforce_read_only,
    }


def _permission_from(d: dict[str, Any]) -> PermissionCtx:
    return PermissionCtx(
        mode=d.get("mode", "default"),
        rules=tuple(_rule_from(r) for r in d.get("rules", ())),
        denylist=frozenset(d.get("denylist", ())),
        approvals=tuple(_approval_from(a) for a in d.get("approvals", ())),
        decisions=tuple(_decision_from(r) for r in d.get("decisions", ())),
        workspace_root=d.get("workspace_root"),
        cwd=d.get("cwd"),
        approval_policy=d.get("approval_policy", "on_request"),
        protect_sensitive_paths=d.get("protect_sensitive_paths", True),
        enforce_read_only=d.get("enforce_read_only", False),
    )


def _error_to(e: ErrorEntry) -> dict[str, Any]:
    return {
        "kind": e.kind.value,
        "layer": e.layer.value,
        "message": e.message,
        "at_turn": e.at_turn,
        "hints": dataclasses.asdict(e.hints),
        "seq": e.seq,
        "timestamp": _dt(e.timestamp),
        "cause": e.cause,
        "context": thaw(e.context) if e.context is not None else None,
        "resumable": e.resumable,
    }


def _error_from(d: dict[str, Any]) -> ErrorEntry:
    return ErrorEntry(
        kind=ErrorKind(d["kind"]),
        layer=ErrorLayer(d["layer"]),
        message=d["message"],
        at_turn=d["at_turn"],
        hints=RecoveryHints(**d.get("hints", {})),
        seq=d.get("seq"),
        timestamp=_parse_dt(d.get("timestamp")),
        cause=d.get("cause"),
        context=d.get("context"),
        resumable=d.get("resumable", False),
    )


def _cp_to(c: Checkpoint) -> dict[str, Any]:
    return {
        "cp_id": c.cp_id,
        "seq": c.seq,
        "turn": c.turn,
        "kind": c.kind,
        "state_digest": c.state_digest,
        "pending": list(c.pending_tool_calls),
        "contract_version": c.contract_version,
    }


def _cp_from(d: dict[str, Any]) -> Checkpoint:
    return Checkpoint(
        cp_id=d["cp_id"],
        seq=d["seq"],
        turn=d["turn"],
        kind=d["kind"],
        state_digest=d["state_digest"],
        pending_tool_calls=tuple(d.get("pending", ())),
        contract_version=d.get("contract_version", 1),
    )


def to_snapshot(run: Run) -> dict[str, Any]:
    """把完整权威 Run 序列化为 JSON-safe dict（不可变叶已 thaw）。"""
    return {
        "contract_version": SNAPSHOT_VERSION,
        "run_id": run.run_id,
        "seq": run.seq,
        "turn": run.turn,
        "status": run.status.value,
        "cancel_reason": run.cancel_reason.value if run.cancel_reason else None,
        "created_at": run.created_at.isoformat(),
        "completed_at": _dt(run.completed_at),
        "budget": dataclasses.asdict(run.budget),
        "items": [_msg_to(m) for m in run.context.items],
        "compaction_floor": run.context.compaction_floor,
        "summary": run.context.summary,
        "recovery_pointers": [list(pair) for pair in run.context.recovery_pointers],
        "task_nodes": [_node_to(n) for n in run.task_tree.nodes],
        "calls": [_call_to(c) for c in run.tool_ledger.calls],
        "checkpoints": [_cp_to(cp) for cp in run.checkpoints],
        "permission": _permission_to(run.permission_ctx),
        "errors": [_error_to(e) for e in run.error_stack],
    }


def _migrate_v1(d: dict[str, Any]) -> dict[str, Any]:
    """v1 明确是有损旧快照：只迁移当时已存在的字段，权限状态回到安全默认。"""
    migrated = dict(d)
    migrated.setdefault("task_nodes", [])
    migrated.setdefault("errors", [])
    migrated.setdefault("compaction_floor", None)
    migrated.setdefault("summary", None)
    migrated.setdefault("recovery_pointers", [])
    # v1 没有 approvals；安全默认是 empty/default permission，而不是伪造历史 decisions。
    migrated.setdefault("permission", {})
    migrated["contract_version"] = SNAPSHOT_VERSION
    return migrated


def from_snapshot(d: dict[str, Any]) -> Run:
    """从 v2 快照重建 Run；v1 做显式有损迁移，未来版本拒绝。"""
    version = int(d.get("contract_version", 0))
    if version < _MIN_SUPPORTED_VERSION:
        raise SnapshotVersionError(f"snapshot contract_version {version} is unsupported")
    if version > SNAPSHOT_VERSION:
        raise SnapshotVersionError(f"snapshot contract_version {version} is newer than Questor can decode")
    if version == 1:
        d = _migrate_v1(d)
    b = d.get("budget", {})
    ctx = Context(
        items=tuple(_msg_from(m) for m in d.get("items", [])),
        compaction_floor=d.get("compaction_floor"),
        summary=d.get("summary"),
        recovery_pointers=tuple(tuple(pair) for pair in d.get("recovery_pointers", ())),
    )
    return Run(
        run_id=d["run_id"],
        seq=d["seq"],
        turn=d["turn"],
        status=RunStatus(d["status"]),
        budget=Budget(**b),
        context=ctx,
        task_tree=TaskTree(nodes=tuple(_node_from(n) for n in d.get("task_nodes", []))),
        tool_ledger=ToolLedger(calls=tuple(_call_from(c) for c in d.get("calls", []))),
        checkpoints=tuple(_cp_from(cp) for cp in d.get("checkpoints", [])),
        permission_ctx=_permission_from(d.get("permission", {})),
        error_stack=tuple(_error_from(e) for e in d.get("errors", [])),
        cancel_reason=CancelReason(d["cancel_reason"]) if d.get("cancel_reason") else None,
        created_at=datetime.fromisoformat(d["created_at"]),
        completed_at=_parse_dt(d.get("completed_at")),
    )


__all__ = [
    "DomainState",
    "SNAPSHOT_VERSION",
    "SnapshotVersionError",
    "from_snapshot",
    "to_snapshot",
]
