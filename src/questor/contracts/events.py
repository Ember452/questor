"""L0 Command / Event vocabulary (design/02; HARD C5/C6/C13).

Iron rules encoded by these shapes:
- Only a :class:`Command` mutates state; an :class:`Event` is a projection and
  must never be fed back as state input (C5).
- Commands are checkable/rejectable (not append-only); Events are append-only and
  irrevocable once emitted (C5).
- Internal events differ from the external projection; consumers ignore unknown
  ``type`` except error-class events (C6).

P0 fixes names + the envelope + correlation keys (locked forever). Exact ``data``
fields stay ``draft`` (C11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from questor.contracts.common import JsonObject, utc_now
from questor.contracts.errors import ErrorEntry
from questor.contracts.state_schema import CancelReason, Checkpoint, Message, TaskNode

#: Association keys — once shipped these are never renamed/removed (design/02 §1).
CORRELATION_KEYS: frozenset[str] = frozenset(
    {"run_id", "turn", "tool_call_id", "card_id", "item_id"}
)

#: Wire-contract version; bump only on a breaking change (design/02 §6).
EVENT_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# Commands (input events) — the only writers, all via ``reduce``.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SubmitMessage:
    run_id: str
    content: Message
    type: ClassVar[str] = "submit_message"


@dataclass(frozen=True, slots=True)
class ProposeAction:
    run_id: str
    turn: int
    # A single-step intent from the PolicyPort (design/05). Untrusted input.
    intent: JsonObject
    type: ClassVar[str] = "propose_action"


@dataclass(frozen=True, slots=True)
class ResolveApproval:
    run_id: str
    tool_call_id: str
    decision: str  # allow | deny  (idempotent; reduce drops repeats, 02 E3)
    type: ClassVar[str] = "resolve_approval"


@dataclass(frozen=True, slots=True)
class Cancel:
    run_id: str
    reason: CancelReason
    type: ClassVar[str] = "cancel"


@dataclass(frozen=True, slots=True)
class WriteMemory:
    run_id: str
    payload: JsonObject
    type: ClassVar[str] = "write_memory"


@dataclass(frozen=True, slots=True)
class RequestCompactHint:
    run_id: str
    # Advisory only; the kernel decides when/how to compact (design/01 I2).
    pressure: float
    type: ClassVar[str] = "request_compact_hint"


Command = (
    SubmitMessage | ProposeAction | ResolveApproval | Cancel | WriteMemory | RequestCompactHint
)


# --------------------------------------------------------------------------- #
# Events (output) — envelope + external projection type names.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Envelope:
    v: int
    seq: int
    run_id: str
    type: str
    ts: datetime = field(default_factory=utc_now)
    turn: int | None = None
    data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 0:
            raise ValueError("Envelope.seq must be >= 0")


class EventType:
    """External event ``type`` names (design/02 §3). Additive only (C6)."""

    RUN_STARTED = "run_started"
    TURN_STARTED = "turn_started"
    TEXT_DELTA = "text_delta"  # live-only, never persisted (I3)
    REASONING_DELTA = "reasoning_delta"  # live-only
    MESSAGE_COMPLETED = "message_completed"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"  # live-only
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUEST = "approval_request"
    NODE_UPDATED = "node_updated"
    USAGE_DELTA = "usage_delta"
    HEARTBEAT = "heartbeat"  # live-only
    RUN_CANCELLED = "run_cancelled"  # precedes run_completed
    RUN_FAILED = "run_failed"
    RUN_COMPLETED = "run_completed"
    RESYNC_REQUIRED = "resync_required"
    WARNING = "warning"  # non-terminal alert (02 §10)


#: Event types that MUST NOT be silently dropped when unknown (C6 exception).
ERROR_CLASS_EVENT_TYPES: frozenset[str] = frozenset(
    {EventType.RUN_FAILED, EventType.WARNING, EventType.RESYNC_REQUIRED}
)


@dataclass(frozen=True, slots=True)
class RunFailedData:
    error: ErrorEntry
    type: ClassVar[str] = EventType.RUN_FAILED


@dataclass(frozen=True, slots=True)
class RunCompletedData:
    final: Message | None = None
    usage: JsonObject | None = None
    exit_reason: str | None = None  # turn_exit_reason (R01 G-1)
    type: ClassVar[str] = EventType.RUN_COMPLETED


@dataclass(frozen=True, slots=True)
class TextDeltaData:
    delta: str
    item_id: str | None = None
    type: ClassVar[str] = EventType.TEXT_DELTA


# Internal domain events (private, may evolve; projected outward). Kept minimal
# in P0; the full internal set is filled with the loop in P1 (design/02 §2/§8).
@dataclass(frozen=True, slots=True)
class NodeUpdated:
    node: TaskNode
    type: ClassVar[str] = EventType.NODE_UPDATED


@dataclass(frozen=True, slots=True)
class CheckpointRecorded:
    checkpoint: Checkpoint
    type: ClassVar[str] = "checkpoint_recorded"


__all__ = [
    "CORRELATION_KEYS",
    "EVENT_SCHEMA_VERSION",
    "SubmitMessage",
    "ProposeAction",
    "ResolveApproval",
    "Cancel",
    "WriteMemory",
    "RequestCompactHint",
    "Command",
    "Envelope",
    "EventType",
    "ERROR_CLASS_EVENT_TYPES",
    "RunFailedData",
    "RunCompletedData",
    "TextDeltaData",
    "NodeUpdated",
    "CheckpointRecorded",
]
