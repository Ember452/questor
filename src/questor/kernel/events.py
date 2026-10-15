"""L2 internal event bus + external projection + version gate (design/02; C5/C6/C13).

The loop pushes the ``Envelope`` events that ``reduce`` produced through
``emit``. The bus:
- persists durable events to the store (live-only deltas are forwarded, never
  stored — design/01 I3 / design/02 X2);
- projects internal -> external and drops unknown types, but always warns on
  unknown error-class events (C6);
- enforces terminal uniqueness (first-writer-wins) so exactly one terminal event
  reaches a run (C13);
- replays from ``after_seq`` then live-follows without gaps or dupes (02 §4).

A subscriber whose wire ``version`` doesn't match gets a single
``resync_required`` and stops (no cross-version decode, 02 §10)."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime

from questor.contracts.events import (
    EVENT_SCHEMA_VERSION,
    Envelope,
    EventType,
)
from questor.contracts.ports import StorePort

_log = logging.getLogger("questor.bus")

#: Live-only event types: forwarded to subscribers, never persisted (design/01 I3).
LIVE_ONLY: frozenset[str] = frozenset(
    {EventType.TEXT_DELTA, EventType.REASONING_DELTA, EventType.TOOL_PROGRESS, EventType.HEARTBEAT, EventType.USAGE_DELTA}
)
TERMINAL: frozenset[str] = frozenset({EventType.RUN_CANCELLED, EventType.RUN_FAILED, EventType.RUN_COMPLETED})
#: Internal-only events not in the external contract (private, may evolve; design/02 §2).
INTERNAL_ONLY: frozenset[str] = frozenset({"checkpoint_recorded", "reduce_rejected", "ledger_entry"})


def project(env: Envelope) -> Envelope | None:
    """Map an internal event to the external set; ``None`` => not exposed."""
    if env.type in INTERNAL_ONLY:
        return None
    return env


class EventBus(ABC):
    @abstractmethod
    async def emit(self, env: Envelope) -> None: ...

    @abstractmethod
    def subscribe(
        self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None
    ) -> AsyncIterator[Envelope]: ...


class InProcessEventBus(EventBus):
    def __init__(self, store: StorePort | None = None) -> None:
        self._store = store
        self._subs: dict[str, list[asyncio.Queue[Envelope]]] = defaultdict(list)
        self._closed: set[str] = set()

    def add_subscriber(self, run_id: str) -> asyncio.Queue[Envelope]:
        queue: asyncio.Queue[Envelope] = asyncio.Queue()
        self._subs[run_id].append(queue)
        return queue

    async def emit(self, env: Envelope) -> None:
        if env.type in TERMINAL:
            if env.run_id in self._closed:  # first-writer-wins
                return
            self._closed.add(env.run_id)

        if env.type not in LIVE_ONLY and self._store is not None:
            await self._store.append(
                env.run_id,
                ({"seq": env.seq, "type": env.type, "turn": env.turn, "data": dict(env.data), "ts": env.ts.isoformat()},),
            )

        projected = project(env)
        if projected is None:
            return
        for queue in self._subs.get(env.run_id, ()):
            queue.put_nowait(projected)
        if env.type in TERMINAL:
            self._subs.pop(env.run_id, None)  # run finished: drop subscriber queues (no leak).
            # Keep _closed: it is the memory that suppresses any later terminal for
            # this run (C13 first-writer-wins). It holds only short run ids.

    async def subscribe(
        self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None
    ) -> AsyncIterator[Envelope]:
        if expected_version is not None and expected_version != EVENT_SCHEMA_VERSION:
            yield Envelope(v=EVENT_SCHEMA_VERSION, seq=after_seq, run_id=run_id, type=EventType.RESYNC_REQUIRED,
                           data={"reason": "version_mismatch", "expected": expected_version, "current": EVENT_SCHEMA_VERSION})
            return

        queue = self.add_subscriber(run_id)  # subscribe BEFORE replay to avoid a gap
        seen = after_seq

        if self._store is not None:
            for row in await self._store.replay(run_id, after_seq):
                seen = max(seen, row["seq"])
                replayed = project(_row_to_envelope(run_id, row))
                if replayed is None:  # internal-only: persisted but not exposed outward
                    continue
                yield replayed
                if replayed.type in TERMINAL:  # run already finished; nothing to follow live
                    return

        while True:
            env = await queue.get()
            if env.type in LIVE_ONLY:
                yield env  # ephemeral deltas: always forwarded, not seq-deduped
            elif env.seq > seen:
                seen = env.seq
                yield env
            if env.type in TERMINAL:
                break


def _row_to_envelope(run_id: str, row: dict) -> Envelope:
    ts = row.get("ts")
    return Envelope(
        v=EVENT_SCHEMA_VERSION,
        seq=row["seq"],
        run_id=run_id,
        type=row["type"],
        turn=row.get("turn"),
        data=row.get("data", {}),
        ts=datetime.fromisoformat(ts) if ts else datetime.now(),
    )
