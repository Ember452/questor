"""L5 StorePort -> SQLite: append-only event log + checkpoints (ADR-0005/0011).

My own implementation of the pattern DeepCode validated (see R03/R10): per-run
logical ``seq`` via ``COALESCE(MAX(seq),0)+1 WHERE run_id`` and ``replay(after_seq)``
are the durable-cursor backbone for ``after_seq`` resume and replay. The write
path uses ``BEGIN IMMEDIATE`` to serialize the single writer (C2). JSON is stored
with ``allow_nan=False``; timestamps are tz-aware UTC (R03 B-P3).

``aiosqlite`` is imported only here (ruff banned-api exempts ``providers/*``)."""

from __future__ import annotations

import json

import aiosqlite

from questor.contracts.common import JsonObject, utc_now
from questor.contracts.ports import StorePort

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    run_id   TEXT    NOT NULL,
    seq      INTEGER NOT NULL,
    type     TEXT    NOT NULL,
    turn     INTEGER,
    item_id  TEXT,
    payload  TEXT    NOT NULL,
    ts       TEXT    NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_replay ON event_log (run_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
    cp_id          TEXT    PRIMARY KEY,
    run_id         TEXT    NOT NULL,
    seq            INTEGER NOT NULL,
    turn           INTEGER NOT NULL,
    kind           TEXT    NOT NULL,
    state_digest   TEXT    NOT NULL,
    pending        TEXT    NOT NULL,
    ts             TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cp_run ON checkpoints (run_id, seq);
"""


def _dumps(obj: object) -> str:
    return json.dumps(obj, allow_nan=False, separators=(",", ":"), ensure_ascii=False)


class SQLiteStore(StorePort):
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> SQLiteStore:
        # isolation_level=None -> autocommit so we can drive BEGIN IMMEDIATE ourselves.
        self._db = await aiosqlite.connect(self.path, isolation_level=None)
        await self._db.executescript(_SCHEMA)
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _dbp(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteStore.connect() must be awaited before use")
        return self._db

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int:
        db = self._dbp()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
            seq = (await cur.fetchone())[0]
            for ev in events:
                # reduce owns the authoritative per-run seq; honor it when present,
                # otherwise append after the current head (ADR-0011).
                seq = int(ev["seq"]) if "seq" in ev else seq + 1
                await db.execute(
                    "INSERT INTO event_log (run_id, seq, type, turn, item_id, payload, ts) VALUES (?,?,?,?,?,?,?)",
                    (
                        run_id,
                        seq,
                        ev["type"],
                        ev.get("turn"),
                        ev.get("item_id"),
                        _dumps(ev.get("data", {})),
                        ev.get("ts") or utc_now().isoformat(),
                    ),
                )
            await db.commit()
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        return seq

    async def replay(self, run_id: str, after_seq: int, limit: int | None = None) -> list[JsonObject]:
        db = self._dbp()
        sql = "SELECT seq, type, turn, item_id, payload, ts FROM event_log WHERE run_id = ? AND seq > ? ORDER BY seq"
        params: tuple = (run_id, after_seq)
        if limit is not None:
            sql += " LIMIT ?"
            params = (run_id, after_seq, limit)
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [
            {"seq": r[0], "type": r[1], "turn": r[2], "item_id": r[3], "data": json.loads(r[4]), "ts": r[5]}
            for r in rows
        ]

    async def sequence_head(self, run_id: str) -> int:
        cur = await self._dbp().execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
        return (await cur.fetchone())[0]

    async def save_checkpoint(self, checkpoint: JsonObject) -> None:
        await self._dbp().execute(
            "INSERT OR REPLACE INTO checkpoints (cp_id, run_id, seq, turn, kind, state_digest, pending, ts) VALUES (?,?,?,?,?,?,?,?)",
            (
                checkpoint["cp_id"],
                checkpoint["run_id"],
                checkpoint["seq"],
                checkpoint["turn"],
                checkpoint["kind"],
                checkpoint["state_digest"],
                _dumps(checkpoint.get("pending", [])),
                checkpoint.get("ts") or utc_now().isoformat(),
            ),
        )

    async def latest_checkpoint(self, run_id: str) -> JsonObject | None:
        cur = await self._dbp().execute(
            "SELECT cp_id, run_id, seq, turn, kind, state_digest, pending, ts FROM checkpoints WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "cp_id": row[0],
            "run_id": row[1],
            "seq": row[2],
            "turn": row[3],
            "kind": row[4],
            "state_digest": row[5],
            "pending": json.loads(row[6]),
            "ts": row[7],
        }
