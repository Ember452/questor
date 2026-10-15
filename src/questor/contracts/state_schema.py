"""L0 state vocabulary: value objects + enums shared by state (L1) and policy (L4).

These live in ``contracts`` (innermost) so both inner and outer layers can import
them without a cycle (STRUCTURE §2). Only **shapes + local invariants** here; the
cross-object invariants and the ``reduce`` writer live in :mod:`questor.state`
(design/01 §12 I1). Field detail stays ``draft`` until P1 (C11) — seam names and
correlation keys are what P0 locks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from questor.contracts.common import JsonObject, require_aware, utc_now


class RunStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"

    @property
    def is_terminal(self) -> bool:
        return self in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.COMPLETED}


class CancelReason(StrEnum):
    """Unified enum across design/02 §5 / 04 §2 / HARD C7 (fixes D8 drift)."""

    USER = "user"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_PROGRESS = "no_progress"
    SAFETY = "safety"
    OWNER = "owner"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ToolCallStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CRITICAL_ERROR = "critical_error"
    DENIED = "denied"


class TaskStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Reserved for multi-agent aggregation (design/01 §13); unused in v1.
    WAITING_CHILDREN = "waiting_children"


class TaskKind(StrEnum):
    TASK = "task"
    SUBAGENT = "subagent"  # placeholder until P8 (design/01 §3)


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """One block in a message: text | reasoning | tool_use | tool_result | ...

    ``type`` selects which optional fields are meaningful; kept as one shape in
    P0 to stay additive-friendly (image/file blocks reuse ``payload``)."""

    type: str  # "text" | "reasoning" | "tool_use" | "tool_result" | "image" | "file"
    text: str | None = None
    tool_use_id: str | None = None  # link for tool_use/tool_result pairing
    name: str | None = None  # tool name (tool_use)
    input: JsonObject | None = None  # tool args (tool_use)
    is_error: bool | None = None  # tool_result flag
    payload: dict[str, Any] | None = None  # image/file opaque carrier
    provider_state: dict[str, Any] | None = None  # opaque, reducer-agnostic (R03 A-2)


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    role: Role
    content: tuple[ContentBlock, ...]
    seq: int
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.seq < 0:
            raise ValueError("Message.seq must be >= 0")
        require_aware(self.created_at, "Message.created_at")


@dataclass(frozen=True, slots=True)
class TaskNode:
    id: str
    title: str
    objective: str = ""
    parent_id: str | None = None  # forest; top-level node => None
    kind: TaskKind = TaskKind.TASK
    status: TaskStatus = TaskStatus.PENDING
    deps: tuple[str, ...] = ()  # v1: read-only validation only (design/01 I6)
    assigned_run_id: str | None = None
    result: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool_call_id: str
    turn: int
    name: str
    args: JsonObject
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Any | None = None
    display: Any | None = None
    permission_decision: str | None = None
    node_id: str | None = None
    seq_request: int | None = None
    seq_result: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Checkpoint:
    cp_id: str
    seq: int
    turn: int
    kind: str  # auto | manual | pre_tool | post_tool | pre_compact
    state_digest: str
    # Interrupted, unclosed tool_use for repair (design/01 §5).
    pending_tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionRule:
    pattern: str
    action: str  # allow | ask | deny
    scope: str = "*"


@dataclass(frozen=True, slots=True)
class Budget:
    max_turns: int = 25
    max_tokens: int | None = None
    deadline_seconds: float | None = None
    # Guard thresholds are configurable (design/04 L4), never hardcoded.
    repeat_tool_limit: int = 3
    max_consecutive_continuations: int = 8
