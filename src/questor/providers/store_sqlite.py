"""L5 StorePort adapter → SQLite (ADR-0005/0011). P0 = class seam, no IO.

The append-only `event_log` (per-run logical seq + global physical rowid,
`replay(after_seq)`, `BEGIN IMMEDIATE` single-writer) is P1 T9, adapted from
DeepCode ``core/persistence/event_repository.py``. `sqlite3`/`aiosqlite` import
only here (ruff banned-api exempts ``providers/*``)."""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.ports import StorePort


class SQLiteStore(StorePort):
    def __init__(self, path: str) -> None:
        self.path = path

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int:
        raise NotImplementedError("event-sourcing append lands in P1 (T9)")

    async def replay(
        self, run_id: str, after_seq: int, limit: int | None = None
    ) -> list[JsonObject]:
        raise NotImplementedError("after_seq replay lands in P1 (T9)")

    async def sequence_head(self, run_id: str) -> int:
        raise NotImplementedError("sequence head lands in P1 (T9)")


__all__ = ["SQLiteStore"]
