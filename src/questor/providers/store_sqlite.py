"""L5 StorePort -> SQLite：append-only 事件日志 + checkpoint（ADR-0005/0011）。

我按 DeepCode 验证过的模式自写的实现（见 R03/R10）：per-run 逻辑 seq 经
``COALESCE(MAX(seq),0)+1 WHERE run_id``、``replay(after_seq)`` 支撑续传与回放。写路径
用 ``BEGIN IMMEDIATE`` 序列化单写者（C2）。JSON 以 ``allow_nan=False`` 存、时间为
tz-aware UTC（R03 B-P3）。``aiosqlite`` 只在此 import（ruff banned-api 对 providers/* 豁免）。
"""

from __future__ import annotations

import json

import aiosqlite

from questor.contracts.common import JsonObject, thaw, utc_now
from questor.contracts.ports import StorePort

# 单一 schema authority、幂等 DDL（IF NOT EXISTS）；event_log 以 (run_id,seq) 复合主键
# 保证 per-run 单调不重，checkpoint 表按 (run_id,seq) 索引供取最近快照。
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
    """序列化为 JSON：先 thaw 不可变叶，禁 NaN/Inf、紧凑分隔符。"""
    return json.dumps(thaw(obj), allow_nan=False, separators=(",", ":"), ensure_ascii=False)


class SQLiteStore(StorePort):
    """StorePort 的 SQLite 适配器。用前先 ``await connect()``。"""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> SQLiteStore:
        # isolation_level=None -> 自动提交，好让我们自己驱动 BEGIN IMMEDIATE。
        self._db = await aiosqlite.connect(self.path, isolation_level=None)
        await self._db.executescript(_SCHEMA)
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _dbp(self) -> aiosqlite.Connection:
        """返回已连接的库；未 connect 则明确报错（而非静默 None）。"""
        if self._db is None:
            raise RuntimeError("SQLiteStore.connect() must be awaited before use")
        return self._db

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int:
        """事务内批量追加，返回最后一个 seq。

        seq 权威在 reduce：事件带 ``seq`` 就沿用之，否则接在当前 head 之后（ADR-0011）。
        """
        db = self._dbp()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
            seq = (await cur.fetchone())[0]
            for ev in events:
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
        """重放 ``seq > after_seq`` 的事件、按 seq 升序——即 after_seq 续传的机制核心。"""
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
        """返回该 run 当前 durable 序列号头部（无事件则 0）。"""
        cur = await self._dbp().execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
        return (await cur.fetchone())[0]

    async def save_checkpoint(self, checkpoint: JsonObject) -> None:
        """写入/覆盖一个 checkpoint（幂等：cp_id 主键 + OR REPLACE）。"""
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
        """返回该 run seq 最大的 checkpoint（供 resume 取最近快照）；无则 None。"""
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
