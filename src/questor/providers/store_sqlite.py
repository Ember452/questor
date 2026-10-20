"""L5 StorePort -> SQLite：append-only 事件日志 + checkpoint（ADR-0005/0011/0020/0022）。

本实现自写，核心设计模式如下：
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

import asyncio
import json
import os
import time

import aiosqlite

from questor.contracts.common import JsonObject, new_id, thaw, utc_now
from questor.contracts.ports import StorePort
from questor.contracts.submissions import (
    MAX_QUEUE_ITEMS,
    SUBMISSIONS_DDL,
    CommandDigestConflict,
    SubmissionConflictError,
    SubmissionQueueFullError,
    canonical_json,
    normalize_source,
)
from questor.kernel.command_window import MAX_WINDOW_ROWS, WINDOW_MIN_ROWS, global_trim_plan, trim_plan

#: 本仓 store DDL 的版本；读到更高版本即 fail-closed（不猜测半升级表形）。
STORE_SCHEMA_VERSION = 4

#: 一轮至多一个终态事件（C13）；某 run 若已落其一，则不再视为"可续跑的未完成 run"。
_TERMINAL_TYPES = ("run_completed", "run_cancelled", "run_failed")

#: B11：v3 实装的四平台；其余为开放词表但义务行置 undeliverable（sweep 不投）。
_DELIVERABLE_PLATFORMS: frozenset[str] = frozenset({"desktop", "http", "openai", "cli"})

#: 五态 + 两个合法终态；``claimed`` 是 attempting 的 legacy 别名（旧 claim_delivery 兼容）。
DELIVERY_STATES: frozenset[str] = frozenset({"pending", "attempting", "acked", "failed", "abandoned", "discarded", "undeliverable"})
_MAX_DELIVERY_ROWS = 500
_PROCESS_START = time.time()

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
    session_id TEXT,
    scope    TEXT    NOT NULL DEFAULT 'run',
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
    updated_at TEXT    NOT NULL,
    session_id TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id  TEXT    PRIMARY KEY,
    state        TEXT    NOT NULL,
    claimed_at   REAL    NOT NULL,
    ttl_seconds  REAL    NOT NULL,
    obligation_id TEXT,
    run_id        TEXT,
    session_id    TEXT,
    ref_kind      TEXT,
    platform      TEXT,
    channel_ref   TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    owner_pid     INTEGER,
    owner_start   REAL,
    recovered     INTEGER NOT NULL DEFAULT 0,
    last_error_class TEXT,
    not_before    REAL,
    last_content_sha TEXT
);
CREATE TABLE IF NOT EXISTS run_leases (
    run_id       TEXT    PRIMARY KEY,
    holder       TEXT    NOT NULL,
    epoch        INTEGER NOT NULL,
    expires_at   REAL    NOT NULL,
    ttl_seconds  REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id           TEXT    PRIMARY KEY,
    title                TEXT,
    kind                 TEXT    NOT NULL DEFAULT 'chat',
    workspace_root       TEXT,
    model                TEXT,
    permission_mode      TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL,
    archived             INTEGER NOT NULL DEFAULT 0,
    pinned               INTEGER NOT NULL DEFAULT 0,
    head_change_version  INTEGER NOT NULL DEFAULT 0,
    last_consolidated    INTEGER NOT NULL DEFAULT 0,
    history_start_seq    INTEGER NOT NULL DEFAULT 0,
    memory_root_mode     TEXT    NOT NULL DEFAULT 'v1',
    next_seq             INTEGER NOT NULL DEFAULT 1,
    metadata_json        TEXT    NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS command_window (
    cseq        INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    session_id  TEXT,
    seq         INTEGER NOT NULL,
    type        TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    idem_key    TEXT    NOT NULL,
    digest      TEXT    NOT NULL,
    accepted    INTEGER NOT NULL,
    ts          TEXT    NOT NULL,
    UNIQUE (run_id, idem_key)
);
CREATE INDEX IF NOT EXISTS idx_cw_run ON command_window (run_id, cseq);
"""


class StoreSchemaVersionError(ValueError):
    """store DDL 版本比本仓可解的更新；连接必须显式失败，绝不半重建（ADR-0022 fail-closed）。"""


class StaleWriterError(RuntimeError):
    """写者不在当前 run 租约上（陈旧 epoch / 无租约却有他人持有）：拒绝落库，绝不双写。

    B0 把 ADR-0047 的"单写者"从 surfaces 约定下推成 store 栅栏：``append`` 在
    ``BEGIN IMMEDIATE`` 事务内比对 ``run_leases``，不匹配即抛本错（fail-closed）。"""


def _dumps(obj: object) -> str:
    """序列化为 JSON：先 thaw 不可变叶，禁 NaN/Inf、紧凑分隔符。"""
    return json.dumps(thaw(obj), allow_nan=False, separators=(",", ":"), ensure_ascii=False)


def delivery_retry_not_before(error_class: str | None, attempts: int, now: float, base: float = 5.0) -> float:
    """错误分类驱动的重试时刻：洪泛/限流/重连走指数退避，其余固定 base。"""
    if error_class in {"flood", "rate_limit", "reconnect", "timeout"}:
        return now + base * (2 ** min(max(0, attempts), 6))
    return now + base


class SQLiteStore(StorePort):
    """StorePort 的 SQLite 适配器。用前先 ``await connect()``。"""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None
        # 单条 aiosqlite 连接上事务不得跨协程交错：BEGIN→…→COMMIT 之间多个 await，
        # 若两个协程同时进入会撞 "cannot start a transaction within a transaction"，其 ROLLBACK
        # 又撕掉对方事务（track4 BLK-1 实测）。此锁在 asyncio 层串行化全部 DB 操作；单连接本就
        # 无法真并发，锁不损吞吐（aiosqlite worker 线程已串行化实际 SQL）。
        self._lock = asyncio.Lock()
        # 本实例**取得/续到**的 run 租约身份（run_id -> (holder, epoch)）：写者出处的唯一来源。
        # 只记录“我拿到的”，不记录“库里当前是谁”——后者在 append 时现查，才能发现陈旧 epoch。
        self._held_leases: dict[str, tuple[str, int]] = {}

    async def connect(self) -> SQLiteStore:
        # isolation_level=None -> 自动提交，好让我们自己驱动 BEGIN IMMEDIATE。
        self._db = await aiosqlite.connect(self.path, isolation_level=None)
        try:
            await self._db.execute("PRAGMA busy_timeout=30000")  # 跨进程 BEGIN IMMEDIATE 瞬时争用下等锁而非立即抛错（#182）；单写者已由租约保证，不开 WAL（收益低、徒增 -wal 文件）。
            await self._db.executescript(_SCHEMA + SUBMISSIONS_DDL)
            await self._enforce_schema_version()
        except BaseException:
            # schema 版本 fail-closed 等抛出时先关掉刚建的连接，避免 aiosqlite 非守护工作线程泄漏（#172）。
            await self._db.close()
            self._db = None
            raise
        return self

    async def _enforce_schema_version(self) -> None:
        """单一 schema authority 的版本闸门：读旧/同版本放行并幂等迁移，读到更新版本 fail-closed。"""
        assert self._db is not None
        cur = await self._db.execute("SELECT value FROM meta WHERE key = 'store_schema_version'")
        row = await cur.fetchone()
        if row is None:
            await self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('store_schema_version', ?)",
                (str(STORE_SCHEMA_VERSION),),
            )
            await self._migrate_columns()
            return
        stored = int(row[0])
        if stored > STORE_SCHEMA_VERSION:
            raise StoreSchemaVersionError(
                f"store schema version {stored} is newer than this build can decode ({STORE_SCHEMA_VERSION}); refusing to half-read"
            )
        await self._migrate_columns()
        if stored < STORE_SCHEMA_VERSION:
            await self._db.execute(
                "UPDATE meta SET value = ? WHERE key = 'store_schema_version'", (str(STORE_SCHEMA_VERSION),)
            )

    async def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        """幂等列迁移：PRAGMA 现查，缺列才 ALTER（不猜测旧表形）。"""
        assert self._db is not None
        cur = await self._db.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        if column not in {row[1] for row in rows}:
            await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    async def _migrate_columns(self) -> None:
        """B4：runs/event_log 的会话列；旧库就地补齐（event_log 旧行 scope 默认 'run'）。"""
        await self._ensure_column("runs", "session_id", "TEXT")
        await self._ensure_column("event_log", "session_id", "TEXT")
        await self._ensure_column("event_log", "scope", "TEXT NOT NULL DEFAULT 'run'")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON event_log (session_id, gseq)")
        # B11：交付义务扩列（旧行保默认值；claim_delivery 的 legacy 语义不变）。
        for column, ddl in (
            ("obligation_id", "TEXT"),
            ("run_id", "TEXT"),
            ("session_id", "TEXT"),
            ("ref_kind", "TEXT"),
            ("platform", "TEXT"),
            ("channel_ref", "TEXT"),
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("owner_pid", "INTEGER"),
            ("owner_start", "REAL"),
            ("recovered", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error_class", "TEXT"),
            ("not_before", "REAL"),
            ("last_content_sha", "TEXT"),
        ):
            await self._ensure_column("deliveries", column, ddl)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _dbp(self) -> aiosqlite.Connection:
        """返回已连接的库；未 connect 则明确报错（而非静默 None）。"""
        if self._db is None:
            raise RuntimeError("SQLiteStore.connect() must be awaited before use")
        return self._db

    async def append(
        self,
        run_id: str,
        events: tuple[JsonObject, ...],
        *,
        holder: str | None = None,
        epoch: int | None = None,
    ) -> int:
        """事务内批量追加，返回最后一个 per-run seq。

        seq 权威在 reduce：事件带 ``seq`` 就沿用之，否则接在当前 head 之后（ADR-0011）。
        每条事件同时取一个全局单调 ``gseq``（跨 run watermark）；``BEGIN IMMEDIATE`` 串行化单写者，
        确保 per-run seq 与全局 gseq 都不重（ADR-0020 append-before-snapshot 的前半）。

        **epoch 栅栏（B0）**：``holder``/``epoch`` 是本写者的租约身份；不给则回落到本实例
        ``acquire_lease`` 记录的身份。只要 ``run_leases`` 中存在该 run 的租约行，写者就必须匹配，
        否则抛 :class:`StaleWriterError`——陈旧驱动者在事务内被拒，绝不静默双写（C2/ADR-0047）。
        无租约行（内存测试/只读回放）保持既有行为；这不是“校验开关”，而是“没人持租约时无竞争”。
        """
        if (holder is None) != (epoch is None):
            raise ValueError("append() requires holder and epoch together")
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._check_writer_fence(db, run_id, holder, epoch)
                if run_id.startswith("sess:"):
                    session_id = run_id[5:]
                    scope = "session"
                else:
                    cur = await db.execute("SELECT session_id FROM runs WHERE run_id = ?", (run_id,))
                    row = await cur.fetchone()
                    session_id = row[0] if row is not None else None
                    scope = "run"
                cur = await db.execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
                seq = (await cur.fetchone())[0]
                for ev in events:
                    seq = int(ev["seq"]) if "seq" in ev else seq + 1
                    await db.execute(
                        "INSERT INTO event_log (run_id, seq, type, turn, item_id, payload, ts, session_id, scope) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            seq,
                            ev["type"],
                            ev.get("turn"),
                            ev.get("item_id"),
                            _dumps(ev.get("data", {})),
                            ev.get("ts") or utc_now().isoformat(),
                            session_id,
                            scope,
                        ),
                    )
                # runs 记账表：派生的快速发现缓存（head_seq + updated_at），非权威真相。
                # session_id 只增不减：先 bind_run_session 再落 run_started 时两处一致。
                await db.execute(
                    "INSERT INTO runs (run_id, head_seq, updated_at, session_id) VALUES (?,?,?,?) "
                    "ON CONFLICT(run_id) DO UPDATE SET head_seq = excluded.head_seq, updated_at = excluded.updated_at, "
                    "session_id = COALESCE(excluded.session_id, runs.session_id)",
                    (run_id, seq, utc_now().isoformat(), session_id),
                )
                await db.commit()
            except BaseException:
                await db.execute("ROLLBACK")
                raise
            return seq

    def writer_identity(self, run_id: str) -> tuple[str, int] | None:
        """本实例在 ``acquire_lease``/``renew_lease`` 时拿到的写者身份；未持租约返回 None。"""
        return self._held_leases.get(run_id)

    async def _check_writer_fence(self, db: aiosqlite.Connection, run_id: str, holder: str | None, epoch: int | None) -> None:
        """事务内校验：有租约行则写者必须匹配（无身份=直接拒），无租约行则放行。"""
        cur = await db.execute("SELECT holder, epoch FROM run_leases WHERE run_id = ?", (run_id,))
        row = await cur.fetchone()
        identity = (holder, epoch) if holder is not None else self._held_leases.get(run_id)
        if identity is None:
            if row is not None:
                raise StaleWriterError(
                    f"run {run_id} is leased to {row[0]!r} (epoch {row[1]}); refusing an unfenced append"
                )
            return
        if row is None or row[0] != identity[0] or row[1] != identity[1]:
            current = None if row is None else (row[0], row[1])
            raise StaleWriterError(
                f"stale writer for run {run_id}: writer holds {identity[0]!r} epoch {identity[1]}, "
                f"lease row is {current!r}; refusing to append"
            )

    async def replay(self, run_id: str, after_seq: int, limit: int | None = None) -> list[JsonObject]:
        """重放 ``seq > after_seq`` 的事件、按 seq 升序——即 after_seq 续传的机制核心。"""
        async with self._lock:
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
        async with self._lock:
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
        async with self._lock:
            cur = await self._dbp().execute("SELECT COALESCE(MAX(gseq), 0) FROM event_log")
            return (await cur.fetchone())[0]

    async def sequence_head(self, run_id: str) -> int:
        """返回该 run 当前 durable 序列号头部（无事件则 0）。"""
        async with self._lock:
            cur = await self._dbp().execute("SELECT COALESCE(MAX(seq), 0) FROM event_log WHERE run_id = ?", (run_id,))
            return (await cur.fetchone())[0]

    async def list_unfinished_runs(self) -> tuple[str, ...]:
        """由 log 派生非终态 run：只认 ``scope='run'``（会话流 ``sess:`` 不混入 ``--list``）。"""
        async with self._lock:
            placeholders = ",".join("?" for _ in _TERMINAL_TYPES)
            cur = await self._dbp().execute(
                f"SELECT DISTINCT run_id FROM event_log WHERE scope = 'run' AND run_id NOT IN "
                f"(SELECT DISTINCT run_id FROM event_log WHERE type IN ({placeholders})) ORDER BY run_id",
                _TERMINAL_TYPES,
            )
            return tuple(r[0] for r in await cur.fetchall())

    # ---- B11：交付义务账本（content-addressed obligation；legacy claim_delivery 语义保留）----
    async def create_obligation(
        self,
        delivery_id: str,
        obligation_id: str,
        platform: str,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        ref_kind: str | None = None,
        channel_ref: str | None = None,
        content_sha: str | None = None,
        now: float | None = None,
    ) -> bool:
        """创建一条投递义务（幂等 by delivery_id）；未实装 platform 置 ``undeliverable``。"""
        state = "pending" if platform in _DELIVERABLE_PLATFORMS else "undeliverable"
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT obligation_id FROM deliveries WHERE delivery_id = ?", (delivery_id,))
                row = await cur.fetchone()
                if row is not None:
                    await db.commit()
                    return row[0] == obligation_id
                await db.execute(
                    "INSERT INTO deliveries (delivery_id, state, claimed_at, ttl_seconds, obligation_id, run_id, session_id, ref_kind, platform, channel_ref, attempts, recovered, last_content_sha) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?)",
                    (delivery_id, state, now or time.time(), 0.0, obligation_id, run_id, session_id, ref_kind, platform, channel_ref, content_sha),
                )
                await db.commit()
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def delivery_row(self, delivery_id: str) -> JsonObject | None:
        """完整交付行（状态机/测试用）；无则 None。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT delivery_id, state, claimed_at, ttl_seconds, obligation_id, run_id, session_id, ref_kind, platform, "
                "channel_ref, attempts, owner_pid, owner_start, recovered, last_error_class, not_before, last_content_sha "
                "FROM deliveries WHERE delivery_id = ?",
                (delivery_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "delivery_id": row[0],
                "state": row[1],
                "claimed_at": row[2],
                "ttl_seconds": row[3],
                "obligation_id": row[4],
                "run_id": row[5],
                "session_id": row[6],
                "ref_kind": row[7],
                "platform": row[8],
                "channel_ref": row[9],
                "attempts": row[10],
                "owner_pid": row[11],
                "owner_start": row[12],
                "recovered": bool(row[13]),
                "last_error_class": row[14],
                "not_before": row[15],
                "last_content_sha": row[16],
            }

    async def claim_delivery(self, delivery_id: str, ttl_seconds: float = 30.0) -> bool:
        """claim-then-deliver（ADR-0047）：原子取投递所有权。``BEGIN IMMEDIATE`` 跨进程串行化。

        新建 claim 返 True；已 acked 或他人未过期持有返 False；前次 claim 超 TTL（崩溃）可重取。"""
        async with self._lock:
            db = self._dbp()
            now = time.time()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT state, claimed_at, ttl_seconds FROM deliveries WHERE delivery_id = ?", (delivery_id,))
                row = await cur.fetchone()
                if row is None:
                    await db.execute("INSERT INTO deliveries (delivery_id, state, claimed_at, ttl_seconds) VALUES (?, 'claimed', ?, ?)", (delivery_id, now, ttl_seconds))
                else:
                    state, claimed_at, ttl = row
                    if state == "acked" or now - claimed_at < ttl:
                        await db.commit()
                        return False
                    await db.execute("UPDATE deliveries SET state = 'claimed', claimed_at = ?, ttl_seconds = ? WHERE delivery_id = ?", (now, ttl_seconds, delivery_id))
                await db.commit()
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def delivery_state(self, delivery_id: str) -> str | None:
        async with self._lock:
            cur = await self._dbp().execute("SELECT state FROM deliveries WHERE delivery_id = ?", (delivery_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def ack_delivery(self, delivery_id: str) -> bool:
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT state FROM deliveries WHERE delivery_id = ?", (delivery_id,))
                row = await cur.fetchone()
                if row is None:
                    await db.commit()
                    return False  # 从未 claim，不能凭空 ack
                if row[0] != "acked":
                    await db.execute("UPDATE deliveries SET state = 'acked' WHERE delivery_id = ?", (delivery_id,))
                await db.commit()
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    # ---- B11：五态机 + 三 sweep + 上限裁剪（账本失败绝不阻塞发送）----
    async def claim_obligation(
        self,
        *,
        now: float | None = None,
        owner_pid: int | None = None,
        owner_start: float | None = None,
        platforms: frozenset[str] | None = None,
    ) -> list[JsonObject]:
        """claim 可投义务：pending/failed-due 首次投；attempting/claimed 崩溃重投置 recovered=1。"""
        stamp = time.time() if now is None else now
        pid = os.getpid() if owner_pid is None else owner_pid
        start = _PROCESS_START if owner_start is None else owner_start
        claimed: list[JsonObject] = []
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT delivery_id, state, claimed_at, ttl_seconds, attempts, platform, not_before FROM deliveries "
                    "WHERE state IN ('pending','claimed','attempting','failed') "
                    "AND (not_before IS NULL OR not_before <= ?) ORDER BY claimed_at",
                    (stamp,),
                )
                for delivery_id, state, claimed_at, ttl, attempts, platform, _not_before in await cur.fetchall():
                    if platforms is not None and platform not in platforms:
                        continue
                    if platform == "undeliverable":
                        continue
                    recovering = state in {"claimed", "attempting"} and (claimed_at + ttl) <= stamp
                    if state in {"claimed", "attempting"} and not recovering:
                        continue  # 他人持有未过期 claim
                    recovered = 1 if recovering else 0
                    await db.execute(
                        "UPDATE deliveries SET state = 'attempting', claimed_at = ?, ttl_seconds = ?, attempts = attempts + 1, "
                        "owner_pid = ?, owner_start = ?, recovered = MAX(recovered, ?), not_before = NULL WHERE delivery_id = ?",
                        (stamp, 30.0, pid, start, recovered, delivery_id),
                    )
                    claimed.append(
                        {
                            "delivery_id": delivery_id,
                            "attempts": int(attempts) + 1,
                            "recovered": bool(recovered),
                            "platform": platform,
                        }
                    )
                await db.commit()
                return claimed
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def finish_delivery(
        self,
        delivery_id: str,
        state: str,
        *,
        error_class: str | None = None,
        not_before: float | None = None,
    ) -> bool:
        """校验五态转移后落终态/失败；abandoned 为不可复活终态。"""
        if state not in DELIVERY_STATES:
            raise ValueError(f"unknown delivery state {state!r}")
        allowed = {
            "pending": {"attempting", "acked", "failed", "abandoned", "discarded", "undeliverable"},
            "claimed": {"attempting", "acked", "failed", "abandoned", "discarded"},
            "attempting": {"attempting", "acked", "failed", "abandoned", "discarded", "undeliverable"},
            "failed": {"pending", "attempting", "abandoned", "discarded"},
            "acked": {"acked"},
            "abandoned": {"abandoned"},
            "discarded": {"discarded"},
            "undeliverable": {"undeliverable"},
        }
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT state FROM deliveries WHERE delivery_id = ?", (delivery_id,))
                row = await cur.fetchone()
                if row is None or state not in allowed.get(row[0], set()):
                    await db.commit()
                    return False
                await db.execute(
                    "UPDATE deliveries SET state = ?, last_error_class = ?, not_before = ? WHERE delivery_id = ?",
                    (state, error_class, not_before, delivery_id),
                )
                await db.commit()
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def sweep_recoverable(self, platforms: frozenset[str], now: float | None = None) -> list[JsonObject]:
        """只对当前可投平台：返回超 TTL 的 in-flight 义务（供重投并带 recovered）。"""
        stamp = time.time() if now is None else now
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT delivery_id, platform, attempts, owner_pid, owner_start FROM deliveries "
                "WHERE state IN ('claimed','attempting') AND claimed_at + ttl_seconds <= ?",
                (stamp,),
            )
            rows = await cur.fetchall()
            return [
                {"delivery_id": r[0], "platform": r[1], "attempts": r[2], "owner_pid": r[3], "owner_start": r[4]}
                for r in rows
                if r[1] in platforms
            ]

    async def sweep_failed_for_runtime(self, now: float | None = None) -> int:
        """把到期的 failed 退回 pending（运行时 sweep；比固定 TTL 更细）。"""
        stamp = time.time() if now is None else now
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "UPDATE deliveries SET state = 'pending', not_before = NULL WHERE state = 'failed' AND not_before IS NOT NULL AND not_before <= ?",
                    (stamp,),
                )
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def pending_retries(self, now: float | None = None) -> int:
        """到期可重试的 failed 条数。"""
        stamp = time.time() if now is None else now
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT COUNT(*) FROM deliveries WHERE state = 'failed' AND not_before IS NOT NULL AND not_before <= ?",
                (stamp,),
            )
            return int((await cur.fetchone())[0])

    async def prune_deliveries(self, max_rows: int = _MAX_DELIVERY_ROWS) -> int:
        """只裁 acked/abandoned/discarded 的旧行；pending/attempting/failed 绝不删。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT COUNT(*) FROM deliveries")
                total = int((await cur.fetchone())[0])
                excess = max(0, total - max_rows)
                if excess == 0:
                    await db.commit()
                    return 0
                cur = await db.execute(
                    "SELECT delivery_id FROM deliveries WHERE state IN ('acked','abandoned','discarded') ORDER BY claimed_at LIMIT ?",
                    (excess,),
                )
                ids = [row[0] for row in await cur.fetchall()]
                if ids:
                    await db.executemany("DELETE FROM deliveries WHERE delivery_id = ?", [(item,) for item in ids])
                await db.commit()
                return len(ids)
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def acquire_lease(self, run_id: str, holder: str, epoch: int, ttl_seconds: float) -> bool:
        """获取 run 驱动租约（单机多进程单写者）：同 holder/已过期可取，他人未过期拒。"""
        async with self._lock:
            db = self._dbp()
            now = time.time()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT holder, epoch, expires_at FROM run_leases WHERE run_id = ?", (run_id,))
                row = await cur.fetchone()
                if row is not None:
                    held_by, held_epoch, expires = row
                    if held_by == holder and held_epoch == epoch:
                        await db.execute("UPDATE run_leases SET expires_at = ?, ttl_seconds = ? WHERE run_id = ?", (now + ttl_seconds, ttl_seconds, run_id))
                        await db.commit()
                        self._held_leases[run_id] = (holder, epoch)
                        return True
                    if now < expires:
                        await db.commit()
                        return False
                await db.execute(
                    "INSERT INTO run_leases (run_id, holder, epoch, expires_at, ttl_seconds) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(run_id) DO UPDATE SET holder=excluded.holder, epoch=excluded.epoch, expires_at=excluded.expires_at, ttl_seconds=excluded.ttl_seconds",
                    (run_id, holder, epoch, now + ttl_seconds, ttl_seconds),
                )
                await db.commit()
                self._held_leases[run_id] = (holder, epoch)
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def renew_lease(self, run_id: str, holder: str, epoch: int) -> bool:
        """续租：仅当前 holder+epoch 匹配时按 ttl 延长到期；否则 False（已被夺走）。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT holder, epoch, ttl_seconds, expires_at FROM run_leases WHERE run_id = ?", (run_id,))
                row = await cur.fetchone()
                if row is None or row[0] != holder or row[1] != epoch:
                    await db.commit()
                    return False
                await db.execute("UPDATE run_leases SET expires_at = ? WHERE run_id = ?", (max(row[3], time.time() + row[2]), run_id))
                await db.commit()
                self._held_leases[run_id] = (holder, epoch)
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def release_lease(self, run_id: str, holder: str, epoch: int) -> bool:
        """释放租约：仅当前 holder+epoch 匹配时删除；否则 False。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT holder, epoch FROM run_leases WHERE run_id = ?", (run_id,))
                row = await cur.fetchone()
                if row is None or row[0] != holder or row[1] != epoch:
                    await db.commit()
                    return False
                await db.execute("DELETE FROM run_leases WHERE run_id = ?", (run_id,))
                await db.commit()
                self._held_leases.pop(run_id, None)
                return True
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def reclaim_expired_leases(self, now: float) -> int:
        """P10/ADR-0050：删已过期 run 租约行（瞬态派生视图）；返回删除数。

        只碰 ``expires_at < now``——持有者本就可重取。BEGIN IMMEDIATE 串行化（C2）。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("DELETE FROM run_leases WHERE expires_at < ?", (now,))
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def reclaim_stale_claims(self, now: float) -> int:
        """P10/ADR-0050：删超 TTL 未 ack 的 in-flight claim（崩溃遗留）。**绝不碰已 acked 行**（BLK-2）。

        只删 ``state='claimed'`` 且 ``claimed_at+ttl_seconds < now``；acked 投递行作幂等键必须保留
        （投递视图从 event_log 重建，删了会 rebuild 重 claim→双投），其回收与 event_log 裁剪绑定后置。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "DELETE FROM deliveries WHERE state = 'claimed' AND claimed_at + ttl_seconds < ?", (now,)
                )
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    # ---- B3：耐久提交队列（session 作用域；写者只碰本表，event_log 仍只由持租约者 append）----
    async def enqueue_submission(
        self,
        session_id: str,
        kind: str,
        payload: JsonObject,
        *,
        source: str,
        idem_key: str,
        digest: str,
        run_id: str | None = None,
    ) -> JsonObject:
        """入队一条提交：同键同 digest 幂等，同键异 digest 拒，队满背压（BEGIN IMMEDIATE 跨进程串行）。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT item_id, digest, change_version FROM submissions WHERE session_id = ? AND idem_key = ?",
                    (session_id, idem_key),
                )
                row = await cur.fetchone()
                if row is not None:
                    if row[1] != digest:
                        raise SubmissionConflictError(
                            f"idempotency key {idem_key!r} in session {session_id!r} is already bound to a different command"
                        )
                    await db.commit()
                    return {"item_id": row[0], "change_version": row[2], "duplicate": True}
                cur = await db.execute(
                    "SELECT COUNT(*) FROM submissions WHERE session_id = ? AND state IN ('pending','deferred')",
                    (session_id,),
                )
                if int((await cur.fetchone())[0]) >= MAX_QUEUE_ITEMS:
                    raise SubmissionQueueFullError(f"session {session_id!r} submission queue is full ({MAX_QUEUE_ITEMS})")
                cur = await db.execute(
                    "SELECT COALESCE(MAX(seq_in_session), 0) FROM submissions WHERE session_id = ?", (session_id,)
                )
                seq_in_session = int((await cur.fetchone())[0]) + 1
                cur = await db.execute("SELECT COALESCE(MAX(change_version), 0) FROM submissions")
                change_version = int((await cur.fetchone())[0]) + 1
                item_id = new_id("sub")
                await db.execute(
                    "INSERT INTO submissions (item_id, session_id, run_id, seq_in_session, kind, payload, source, idem_key, digest, state, change_version, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?, 'pending', ?, ?)",
                    (
                        item_id,
                        session_id,
                        run_id,
                        seq_in_session,
                        kind,
                        canonical_json(thaw(payload)),
                        normalize_source(source),
                        idem_key,
                        digest,
                        change_version,
                        utc_now().isoformat(),
                    ),
                )
                await db.commit()
                return {"item_id": item_id, "change_version": change_version, "duplicate": False}
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def claim_submissions(self, session_id: str, *, limit: int = 100, run_id: str | None = None) -> list[JsonObject]:
        """原子 claim pending/deferred 行（置 deferred + run_id）；按 seq_in_session 升序返回。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT item_id, session_id, run_id, seq_in_session, kind, payload, source, idem_key, change_version "
                    "FROM submissions WHERE session_id = ? AND state IN ('pending','deferred') "
                    "ORDER BY seq_in_session LIMIT ?",
                    (session_id, max(1, limit)),
                )
                rows = await cur.fetchall()
                if rows:
                    await db.executemany(
                        "UPDATE submissions SET state = 'deferred', run_id = COALESCE(?, run_id) WHERE item_id = ?",
                        [(run_id, row[0]) for row in rows],
                    )
                await db.commit()
                return [
                    {
                        "item_id": row[0],
                        "session_id": row[1],
                        "run_id": run_id if run_id is not None else row[2],
                        "seq_in_session": row[3],
                        "kind": row[4],
                        "payload": json.loads(row[5]),
                        "source": row[6],
                        "idem_key": row[7],
                        "change_version": row[8],
                    }
                    for row in rows
                ]
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def ack_submissions(self, item_ids: tuple[str, ...]) -> int:
        """已应用命令置 consumed；返回受影响行数。"""
        if not item_ids:
            return 0
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in item_ids)
                cur = await db.execute(
                    f"UPDATE submissions SET state = 'consumed' WHERE item_id IN ({placeholders})", item_ids
                )
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def release_submissions(self, item_ids: tuple[str, ...]) -> int:
        """未匹配/未应用的 claim 退回 pending（run_id 清空）；返回受影响行数。"""
        if not item_ids:
            return 0
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in item_ids)
                cur = await db.execute(
                    f"UPDATE submissions SET state = 'pending', run_id = NULL WHERE item_id IN ({placeholders})", item_ids
                )
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def submissions_since(self, session_id: str, after_version: int, limit: int = 512) -> list[JsonObject]:
        """``change_version > after_version`` 的队列行（多端观察同一队；升序）。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT item_id, session_id, run_id, seq_in_session, kind, payload, source, idem_key, state, change_version "
                "FROM submissions WHERE session_id = ? AND change_version > ? ORDER BY change_version LIMIT ?",
                (session_id, after_version, max(1, limit)),
            )
            rows = await cur.fetchall()
            return [
                {
                    "item_id": row[0],
                    "session_id": row[1],
                    "run_id": row[2],
                    "seq_in_session": row[3],
                    "kind": row[4],
                    "payload": json.loads(row[5]),
                    "source": row[6],
                    "idem_key": row[7],
                    "state": row[8],
                    "change_version": row[9],
                }
                for row in rows
            ]

    async def pending_submission_count(self, session_id: str) -> int:
        """该会话在途（pending + deferred）条数；入队背压判据。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT COUNT(*) FROM submissions WHERE session_id = ? AND state IN ('pending','deferred')",
                (session_id,),
            )
            return int((await cur.fetchone())[0])

    async def trim_consumed_submissions(self, session_id: str, keep: int = 512) -> int:
        """只回收 consumed 的旧行（保留最近 keep 条）；pending/deferred 绝不删。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "DELETE FROM submissions WHERE session_id = ? AND state = 'consumed' AND item_id NOT IN "
                    "(SELECT item_id FROM submissions WHERE session_id = ? AND state = 'consumed' "
                    "ORDER BY change_version DESC LIMIT ?)",
                    (session_id, session_id, max(0, keep)),
                )
                await db.commit()
                return cur.rowcount or 0
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    # ---- B4：会话作用域（sessions + event_log.scope/session_id；不改 Envelope）----
    async def create_session(
        self,
        session_id: str | None = None,
        *,
        model: str | None = None,
        workspace_root: str | None = None,
        kind: str = "chat",
    ) -> str:
        """新建（或幂等确保）一条会话行；返回 session_id。显式 id 必须非空且 ≤128。"""
        sid = session_id or new_id("sess")
        if not sid or len(sid) > 128:
            raise ValueError("session_id must be non-empty and <= 128 chars")
        now = utc_now().isoformat()
        async with self._lock:
            db = self._dbp()
            await db.execute(
                "INSERT OR IGNORE INTO sessions (session_id, kind, workspace_root, model, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (sid, kind, workspace_root, model, now, now),
            )
            await db.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, sid))
        return sid

    async def ensure_session(self, session_id: str) -> JsonObject:
        """确保会话行存在并返回它（不存在则按默认值新建）。"""
        await self.create_session(session_id)
        row = await self.session_row(session_id)
        assert row is not None
        return row

    async def bind_run_session(self, run_id: str, session_id: str) -> None:
        """把 run 路由到会话：先绑定再落 run_started，event_log.session_id 才不丢。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO runs (run_id, head_seq, updated_at, session_id) VALUES (?, 0, ?, ?) "
                    "ON CONFLICT(run_id) DO UPDATE SET session_id = excluded.session_id, updated_at = excluded.updated_at",
                    (run_id, utc_now().isoformat(), session_id),
                )
                await db.commit()
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def run_session(self, run_id: str) -> str | None:
        """该 run 绑定的 session_id；未绑定返回 None。"""
        async with self._lock:
            cur = await self._dbp().execute("SELECT session_id FROM runs WHERE run_id = ?", (run_id,))
            row = await cur.fetchone()
            return row[0] if row is not None else None

    async def session_row(self, session_id: str) -> JsonObject | None:
        """会话行（metadata_json 解析为 dict）；无则 None。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT session_id, title, kind, workspace_root, model, permission_mode, created_at, updated_at, "
                "archived, pinned, head_change_version, last_consolidated, history_start_seq, memory_root_mode, "
                "next_seq, metadata_json FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "session_id": row[0],
                "title": row[1],
                "kind": row[2],
                "workspace_root": row[3],
                "model": row[4],
                "permission_mode": row[5],
                "created_at": row[6],
                "updated_at": row[7],
                "archived": bool(row[8]),
                "pinned": bool(row[9]),
                "head_change_version": row[10],
                "last_consolidated": row[11],
                "history_start_seq": row[12],
                "memory_root_mode": row[13],
                "next_seq": row[14],
                "metadata": json.loads(row[15]) if row[15] else {},
            }

    async def advance_last_consolidated(self, session_id: str, seq: int) -> int:
        """巩固游标只前进：``last_consolidated = max(old, seq)``；返回受影响行数。"""
        async with self._lock:
            db = self._dbp()
            cur = await db.execute(
                "UPDATE sessions SET last_consolidated = MAX(last_consolidated, ?), updated_at = ? WHERE session_id = ?",
                (seq, utc_now().isoformat(), session_id),
            )
            return cur.rowcount or 0

    async def set_history_start_seq(self, session_id: str, seq: int) -> int:
        """喂入起点只前进（与 last_consolidated 分离，§4.5 双游标）。"""
        async with self._lock:
            db = self._dbp()
            cur = await db.execute(
                "UPDATE sessions SET history_start_seq = MAX(history_start_seq, ?), updated_at = ? WHERE session_id = ?",
                (seq, utc_now().isoformat(), session_id),
            )
            return cur.rowcount or 0

    async def session_events(self, session_id: str, limit: int | None = None) -> list[JsonObject]:
        """该会话的事实流（含 scope/session_id 列；批量传入专用，非对外 wire）。"""
        async with self._lock:
            sql = (
                "SELECT gseq, run_id, seq, type, turn, item_id, payload, ts, session_id, scope "
                "FROM event_log WHERE session_id = ? ORDER BY gseq"
            )
            params: tuple = (session_id,)
            if limit is not None:
                sql += " LIMIT ?"
                params = (session_id, limit)
            cur = await self._dbp().execute(sql, params)
            rows = await cur.fetchall()
            return [
                {
                    "gseq": row[0],
                    "run_id": row[1],
                    "seq": row[2],
                    "type": row[3],
                    "turn": row[4],
                    "item_id": row[5],
                    "data": json.loads(row[6]),
                    "ts": row[7],
                    "session_id": row[8],
                    "scope": row[9],
                }
                for row in rows
            ]

    async def session_transcript(self, session_id: str, limit: int = 8) -> list[JsonObject]:
        """最近 N 条 user/assistant 事实（新→旧），供 SeedContext 取原文。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT gseq, run_id, seq, type, payload, ts FROM event_log "
                "WHERE session_id = ? AND type IN ('user_message','message_completed') ORDER BY gseq DESC LIMIT ?",
                (session_id, max(1, limit)),
            )
            rows = await cur.fetchall()
            return [
                {"gseq": row[0], "run_id": row[1], "seq": row[2], "type": row[3], "data": json.loads(row[4]), "ts": row[5]}
                for row in rows
            ]

    # ---- B2：有界命令窗口（canonical digest；被拒命令不入窗）----
    async def record_command(
        self,
        run_id: str,
        seq: int,
        command_type: str,
        payload: str,
        *,
        source: str,
        idem_key: str,
        digest: str,
        accepted: bool = True,
        session_id: str | None = None,
        ts: str | None = None,
    ) -> JsonObject:
        """记录一条已接受命令：同键同 digest 幂等；同键异 digest 拒（``CommandDigestConflict``）。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT digest, cseq FROM command_window WHERE run_id = ? AND idem_key = ?", (run_id, idem_key)
                )
                row = await cur.fetchone()
                if row is not None:
                    if row[0] != digest:
                        raise CommandDigestConflict(
                            f"command window key {idem_key!r} on run {run_id!r} is already bound to a different digest"
                        )
                    await db.commit()
                    return {"cseq": row[1], "duplicate": True}
                if session_id is None:
                    if run_id.startswith("sess:"):
                        session_id = run_id[5:]
                    else:
                        cur = await db.execute("SELECT session_id FROM runs WHERE run_id = ?", (run_id,))
                        bound = await cur.fetchone()
                        session_id = bound[0] if bound is not None else None
                cur = await db.execute(
                    "INSERT INTO command_window (run_id, session_id, seq, type, payload, source, idem_key, digest, accepted, ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id, session_id, seq, command_type, payload, source, idem_key, digest, 1 if accepted else 0, ts or utc_now().isoformat()),
                )
                await db.commit()
                return {"cseq": cur.lastrowid, "duplicate": False}
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def command_window_rows(
        self, *, run_id: str | None = None, session_id: str | None = None, limit: int | None = None
    ) -> list[JsonObject]:
        """命令窗口行（测试/诊断/裁剪用；按 cseq 升序）。"""
        async with self._lock:
            sql = "SELECT cseq, run_id, session_id, seq, type, payload, source, idem_key, digest, accepted, ts FROM command_window"
            where: list[str] = []
            params: list[object] = []
            if run_id is not None:
                where.append("run_id = ?")
                params.append(run_id)
            if session_id is not None:
                where.append("session_id = ?")
                params.append(session_id)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY cseq"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            cur = await self._dbp().execute(sql, tuple(params))
            rows = await cur.fetchall()
            return [
                {
                    "cseq": row[0],
                    "run_id": row[1],
                    "session_id": row[2],
                    "seq": row[3],
                    "type": row[4],
                    "payload": row[5],
                    "source": row[6],
                    "idem_key": row[7],
                    "digest": row[8],
                    "accepted": bool(row[9]),
                    "ts": row[10],
                }
                for row in rows
            ]

    async def trim_command_window(self, session_id: str) -> int:
        """裁剪窗口：只清 ``last_consolidated`` 之前的段（保最近 MIN 行），再执行全局 MAX 整批 drop。"""
        async with self._lock:
            db = self._dbp()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT last_consolidated FROM sessions WHERE session_id = ?", (session_id,))
                row = await cur.fetchone()
                last = int(row[0]) if row is not None else 0
                cur = await db.execute(
                    "SELECT cseq, run_id, seq FROM command_window WHERE session_id = ? ORDER BY cseq", (session_id,)
                )
                session_rows = [{"cseq": r[0], "run_id": r[1], "seq": r[2]} for r in await cur.fetchall()]
                cur = await db.execute("SELECT cseq, run_id FROM command_window ORDER BY cseq")
                all_rows = [{"cseq": r[0], "run_id": r[1]} for r in await cur.fetchall()]
                doomed = set(trim_plan(session_rows, last, min_rows=WINDOW_MIN_ROWS))
                doomed |= set(global_trim_plan(all_rows, max_rows=MAX_WINDOW_ROWS))
                if doomed:
                    await db.executemany("DELETE FROM command_window WHERE cseq = ?", [(cseq,) for cseq in sorted(doomed)])
                await db.commit()
            except BaseException:
                await db.execute("ROLLBACK")
                raise
        await self.trim_consumed_submissions(session_id)
        return len(doomed)

    async def set_fold_mode(self, session_id: str, mode: str) -> str:
        """代际位：``v1|legacy``（默认 v1）；非法值 fail-closed。"""
        if mode not in {"v1", "legacy"}:
            raise ValueError("fold_mode must be 'v1' or 'legacy'")
        async with self._lock:
            await self._dbp().execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"command_window_fold_mode:{session_id}", mode),
            )
        return mode

    async def fold_mode(self, session_id: str) -> str:
        """读取代际位；未设置 → ``v1``。"""
        async with self._lock:
            cur = await self._dbp().execute(
                "SELECT value FROM meta WHERE key = ?", (f"command_window_fold_mode:{session_id}",)
            )
            row = await cur.fetchone()
            return row[0] if row is not None else "v1"

    async def save_checkpoint(self, checkpoint: JsonObject) -> None:
        """写入/覆盖一个 checkpoint（幂等：cp_id 主键 + OR REPLACE）。

        ADR-0020：调用方须已把该 seq 及之前的耐久事件 append 落库（append-before-snapshot）。
        """
        async with self._lock:
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
        async with self._lock:
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
        async with self._lock:
            cur = await self._dbp().execute("SELECT MAX(seq) FROM checkpoints WHERE run_id = ?", (run_id,))
            row = await cur.fetchone()
            return row[0] if row and row[0] is not None else None
