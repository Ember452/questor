"""L0 error envelope + classification types (design/01 §8; ADR-0010).

ADR-0010: **classification is a pure function living in ``contracts``** (no
provider import); the retry/fallback **orchestration lives in the kernel**. P0
only fixes the shape — the classifier body arrives when errors flow in P1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from questor.contracts.common import JsonObject, require_aware


class ErrorLayer(StrEnum):
    KERNEL = "kernel"
    TOOL = "tool"
    PROVIDER = "provider"
    PERSIST = "persist"


class ErrorKind(StrEnum):
    """Stable, provider-neutral error namespace (external ``error.code``)."""

    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    CONTEXT_OVERFLOW = "context_overflow"
    CONTEXT_MEMORY_CEILING = "context_memory_ceiling"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    FORMAT_ERROR = "format_error"
    AUTH = "auth"
    BILLING = "billing"
    MODEL_NOT_FOUND = "model_not_found"
    CANCELLED = "cancelled"
    POLICY_VIOLATION = "policy_violation"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class RecoveryHints:
    """Orthogonal recovery switches (R08 A-1) — not a single ``retryable`` bool.

    P0 keeps all-False defaults; the classifier that fills them is P1+ / P10.
    """

    retryable: bool = False
    should_compress: bool = False
    should_fallback: bool = False
    should_rotate_credential: bool = False


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    """Normalized error recorded on ``run.error_stack`` (design/01 §8)."""

    kind: ErrorKind
    layer: ErrorLayer
    message: str
    at_turn: int
    hints: RecoveryHints
    seq: int | None = None
    timestamp: datetime | None = None
    cause: str | None = None
    context: JsonObject | None = None
    resumable: bool = False

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            require_aware(self.timestamp, "ErrorEntry.timestamp")
