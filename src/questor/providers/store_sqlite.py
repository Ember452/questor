"""L5 StorePort -> SQLite：append-only 事件日志 + checkpoint（ADR-0005/0011/0020/0022）。

我按 DeepCode 验证过的模式自写的实现（见 R03/R10）：
- **两类游标**（ADR-0011/0022）：per-run 逻辑 ``seq``（``SSE after_seq`` 续传，
  ``COALESCE(MAX(seq),0)+1 WHERE run_id``）+ 全局单调物理 ``gseq``（跨 run catch-up watermark）。
- **log 权威（事件）+ 快照权威（状态）**（ADR-0020）：耐久事件先经 ``BEGIN IMMEDIATE`` 原子落
  ``event_log``，再由调用方写 ``checkpoints``。``event_log`` 是耐久**事件**的唯一真相（客户端重放 + 审计）；
  权威**状态**由快照承载——``rebuild_run`` 从**最近完好快照**重建、损坏则**回退次近完好快照**、无一完好则
  fail-closed 抛错（输出事件是投影，**不可 reduce 回灌状态**，C5）。
- **单一 schema authority + 幂等 DDL + 版本 fail-closed**（R03 E-P1/ADR-0022）：``meta`` 表存
  ``store_schema_version``；读到比本仓能解的更新 → 显式 ``StoreSchemaVersionError``，绝不半重建。
- **非终态发现**：``list_unfinished_runs`` 由 ``event_log`` 是否含终态事件派生（log 权威，不靠旁记 status）。

JSON 以 ``allow_nan=False`` 存、时间为 tz-aware UTC（R03 B-P3）。``aiosqlite`` 只在此 import
（ruff banned-api 对 providers/* 豁免）。
"""

from __future__ import annotations

import json

import aiosqlite

from questor.contracts.common import JsonObject, thaw, utc_now
from questor.contracts.ports import StorePort

#: 本仓 store DDL 的版本；读到更高版本即 fail-closed（不猜测半升级表形）。
STORE_SCHEMA_VERSION = 2

#: 一轮至多一个终态事件（C13）；某 run 若已落其一，则不再视为"可续跑的未完成 run"。
_TERMINAL_TYPES = ("run_completed", "run_cancelled", "run_failed")

# 单一 schema authority、幂等 DDL（IF NOT EXISTS）。
# event_log：per-run 逻辑 seq 复合主键保证不重，全局 gseq 单调物理序供跨 run watermark。
# checkpoints：按 (run_id,seq) 索引取最近快照。runs：派生记账（head_seq 供快速发现）。
# meta：store_schema_version 等元数据。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    gseq     INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT    NOT NULL,
    seq      INTEGER NOT NULL,
    type     TEXT    NOT NULL,
    turn     INTEGER,
    item_id  TEXT,
    payload  TEXT    NOT NULL,
    ts       TEXT    NOT NULL,
    UNIQUE (run_id, seq)
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
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT    PRIMARY KEY,
    head_seq   INTEGER NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class StoreSchemaVersionError(ValueError):
    """store DDL 版本比本仓可解的更新；连接必须显式失败，绝不半重建（ADR-0022 fail-closed）。"""


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
        await self._enforce_schema_version()
        return self

    async def _enforce_schema_version(self) -> None:
        """单一 schema authority 的版本闸门：读旧/同版本放行，读到更新版本 fail-closed。"""
        assert self._db is not None
        cur = await self._db.execute("SELECT value FROM meta WHERE key = 'store_schema_version'")
        row = await cur.fetchone()
        if row is None:
            await self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('store_schema_version', ?)",
                (str(STORE_SCHEMA_VERSION),),
            )
            return
        stored = int(row[0])
        if stored > STORE_SCHEMA_VERSION:
            raise StoreSchemaVersionError(
                f"store schema version {stored} is newer than this build can decode ({STORE_SCHEMA_VERSION}); refusing to half-read"
            )
        # stored <= STORE_SCHEMA_VERSION：pre-alpha 不做向前迁移，放行（DDL 幂等 IF NOT EXISTS）。

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
        """事务内批量追加，返回最后一个 per-run seq。

        seq 权威在 reduce：事件带 ``seq`` 就沿用之，否则接在当前 head 之后（ADR-0011）。
        每条事件同时取一个全局单调 ``gseq``（跨 run watermark）；``BEGIN IMMEDIATE`` 串行化单写者，
        确保 per-run seq 与全局 gseq 都不重（ADR-0020 append-before-snapshot 的前半）。
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
            # runs 记账表：派生的快速发现缓存（head_seq + updated_at），非权威真相。
            await db.execute(
                "INSERT INTO runs (run_id, head_seq, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET head_seq = excluded.head_seq, updated_at = excluded.updated_at",
                (run_id, seq, utc_now().isoformat()),
            )
            await db.commit()
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        return seq

    async def replay(self, run_id: str, after_seq: int, limit: int | None = None) -> list[JsonObject]:
        """重放 ``seq > after_seq`` 的事件、按 seq 升序——即 after_seq 续传的机制核心。"""
        db = self._dbp()
        sql = "SELECT gseq, seq, type, turn, item_id, payload, ts FROM event_log WHERE run_id = ? AND seq > ? ORDER BY seq"
        params: tuple = (run_id, after_seq)
        if limit is not None:
            sql += " LIMIT ?"
            params = (run_id, after_seq, limit)
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [
            {"gseq": r[0], "seq": r[1], "type": r[2], "turn": r[3], "item_id": r[4], "data": json.loads(r[5]), "ts": r[6]}
            for r in rows
        ]

    async def replay_global(self, after_watermark: int, limit: int | None = None) -> list[JsonObject]:
        """跨 run 重放全局 ``gseq > after_watermark`` 的事件、按全局序升序（catch-up watermark）。"""
        db = self._dbp()
        sql = (
            "SELECT gseq, run_id, seq, type, turn, item_id, payload, ts FROM event_log WHERE gseq > ? ORDER BY gseq"
        )
        params: tuple = (after_watermark,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (after_watermark, limit)
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [
            {
                "gseq": r[0],
                "run_id": r[1],
                "seq": r[2],
                "type": r[3],
                "turn": r[4],
                "item_id": r[5],
                "data": json.loads(r[6]),
                "ts": r[7],
            }
            for r in rows
        ]

    async def watermark(self) -> int:
        """当前全局物理序头部（无事件则 0）。"""
        cur = await self._dbp().execute("SELECT COALESCE(MAX(gseq), 0) FROM event_log")
        return (await cur.fetchone())[0]

    async def sequence_head(self, run_id: str) -> int:
        """返回该 run 当前 durable 序列号头部（无事件则 0）。"""
        cur = await self._dbp().execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
        return (await cur.fetchone())[0]

    async def list_unfinished_runs(self) -> tuple[str, ...]:
        """由 log 派生非终态 run：有事件但 event_log 中不含任一终态事件（log 权威，不旁记 status）。"""
        placeholders = ",".join("?" for _ in _TERMINAL_TYPES)
        cur = await self._dbp().execute(
            f"SELECT DISTINCT run_id FROM event_log WHERE run_id NOT IN "
            f"(SELECT DISTINCT run_id FROM event_log WHERE type IN ({placeholders})) ORDER BY run_id",
            _TERMINAL_TYPES,
        )
        return tuple(r[0] for r in await cur.fetchall())

    async def save_checkpoint(self, checkpoint: JsonObject) -> None:
        """写入/覆盖一个 checkpoint（幂等：cp_id 主键 + OR REPLACE）。

        ADR-0020：调用方须已把该 seq 及之前的耐久事件 append 落库（append-before-snapshot）。
        """
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
        rows = await self.checkpoints(run_id, limit=1)
        return rows[0] if rows else None

    async def checkpoints(self, run_id: str, limit: int | None = None) -> list[JsonObject]:
        """该 run 快照列表，**按 seq 新→旧**；供 ``rebuild_run`` 逐一尝试完好快照、跳过损坏项。"""
        sql = "SELECT cp_id, run_id, seq, turn, kind, state_digest, pending, ts FROM checkpoints WHERE run_id = ? ORDER BY seq DESC"
        params: tuple = (run_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (run_id, limit)
        cur = await self._dbp().execute(sql, params)
        rows = await cur.fetchall()
        return [
            {
                "cp_id": r[0],
                "run_id": r[1],
                "seq": r[2],
                "turn": r[3],
                "kind": r[4],
                "state_digest": r[5],
                "pending": json.loads(r[6]) if r[6] else [],
                "ts": r[7],
            }
            for r in rows
        ]

    async def checkpoint_seq(self, run_id: str) -> int | None:
        """该 run 最近快照的 seq（尾重放起点）；无快照返回 None。"""
        cur = await self._dbp().execute("SELECT MAX(seq) FROM checkpoints WHERE run_id = ?", (run_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] is not None else None
