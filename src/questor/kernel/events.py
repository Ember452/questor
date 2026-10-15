"""L2 internal event bus + projection seam (design/02; HARD C5/C6/C13).

Only ``Command`` mutates state; the bus emits append-only ``Event``s that are
irrevocable once sent. Internal events are projected to the stable external set.
Body (durable seq allocation, terminal uniqueness) is P1 (T7/T8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from questor.contracts.common import JsonObject


class EventBus(ABC):
    """Typed internal bus: submit Commands, subscribe to projected events."""

    @abstractmethod
    async def submit(self, command_type: str, payload: JsonObject) -> int:
        """Accept a Command; allocate its durable seq (02 §10). Returns seq."""

    @abstractmethod
    def subscribe(self, run_id: str, after_seq: int = 0) -> AsyncIterator[JsonObject]:
        """Stream external events for a run from ``after_seq`` (SSE resume)."""
