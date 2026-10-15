"""L1 Domain_State aggregate (design/01). P0 = shapes + constructor invariants.

The single authoritative, immutable, replayable state. This module composes the
L0 vocabulary into ``Run`` / ``Session`` and enforces *local* invariants at
construction time (DeepCode ``domain/turn.py`` pattern). The cross-object
invariants (``tool_use``<->``tool_result`` pairing, DAG acyclicity) and the sole
writer ``reduce`` are **P1** (design/01 §12 I1; plan/01 T3) — not here.

Immutable discipline (C2): every collection is a ``tuple``/``frozenset``; a
frozen dataclass with tuple fields is deep-readonly, unlike a shallow freeze.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from questor.contracts.common import require_aware, utc_now
from questor.contracts.errors import ErrorEntry
from questor.contracts.state_schema import (
    Budget,
    CancelReason,
    Checkpoint,
    Message,
    PermissionRule,
    RunStatus,
    TaskNode,
    ToolCall,
)


@dataclass(frozen=True, slots=True)
class Context:
    """Conversation context + compaction boundary (design/01 §2)."""

    items: tuple[Message, ...] = ()
    compaction_floor: int | None = None
    summary: str | None = None
    recovery_pointers: tuple[tuple[int, int], ...] = ()  # (seq_from, seq_to) ranges


@dataclass(frozen=True, slots=True)
class TaskTree:
    """Forest of nodes (v1 = strict forest; DAG deferred, I6)."""

    nodes: tuple[TaskNode, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolLedger:
    calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionDecisionRecord:
    tool_call_id: str
    decision: str  # allow | ask | deny
    decided_by: str  # rule | user
    at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PermissionCtx:
    """Three-valued permission context (design/01 §6; decision/eval in kernel)."""

    mode: str = "default"  # default | plan | full_auto
    rules: tuple[PermissionRule, ...] = ()
    denylist: frozenset[str] = frozenset()  # non-overridable sensitive paths
    decisions: tuple[PermissionDecisionRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class Run:
    """One execution — the checkpoint / replay / resume unit (design/01 §1)."""

    run_id: str
    seq: int = 0
    turn: int = 0
    status: RunStatus = RunStatus.IDLE
    budget: Budget = field(default_factory=Budget)
    context: Context = field(default_factory=Context)
    task_tree: TaskTree = field(default_factory=TaskTree)
    tool_ledger: ToolLedger = field(default_factory=ToolLedger)
    checkpoints: tuple[Checkpoint, ...] = ()
    permission_ctx: PermissionCtx = field(default_factory=PermissionCtx)
    error_stack: tuple[ErrorEntry, ...] = ()
    cancel_reason: CancelReason | None = None
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        # Local, cheap invariants only. Sequence must never go backwards.
        if self.seq < 0:
            raise ValueError("Run.seq must be >= 0")
        if self.turn < 0:
            raise ValueError("Run.turn must be >= 0")
        require_aware(self.created_at, "Run.created_at")
        # Terminal-state consistency (R03/C13; mirrors DeepCode turn.py).
        if self.status.is_terminal:
            if self.completed_at is None:
                raise ValueError("terminal Run requires completed_at")
            if self.status is RunStatus.CANCELLED and self.cancel_reason is None:
                raise ValueError("cancelled Run requires cancel_reason")
            if self.status is RunStatus.FAILED and not self.error_stack:
                raise ValueError("failed Run requires a non-empty error_stack")
        else:
            if self.completed_at is not None:
                raise ValueError("non-terminal Run cannot have completed_at")
            if self.cancel_reason is not None:
                raise ValueError("non-terminal Run cannot carry cancel_reason")


@dataclass(frozen=True, slots=True)
class SessionDefaults:
    """Per-session defaults (immutable; design/01 §1)."""

    model: str | None = None
    locale: str = "en"
    permission_mode: str = "default"


@dataclass(frozen=True, slots=True)
class DomainState:
    """Session root = the authoritative per-user conversation line (§1)."""

    session_id: str
    runs: tuple[Run, ...] = ()
    defaults: SessionDefaults = field(default_factory=SessionDefaults)

    def active_run(self, run_id: str) -> Run | None:
        """Read-only lookup (no mutation)."""
        return next((r for r in self.runs if r.run_id == run_id), None)


__all__ = [
    "Context",
    "TaskTree",
    "ToolLedger",
    "PermissionDecisionRecord",
    "PermissionCtx",
    "Run",
    "DomainState",
    "SessionDefaults",
]
