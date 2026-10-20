"""L5 MemoryStorePort -> SQLite（独立 ``memory.db``；ADR-0023/0025/0026）。

按 P3 :mod:`questor.providers.store_sqlite` 验证过的纪律自写：单一 ``_SCHEMA`` authority +
幂等 DDL（``IF NOT EXISTS``）+ ``meta(memory_schema_version)`` 未知更新版本 fail-closed +
``BEGIN IMMEDIATE`` 串行单写者。与 event-log **分库**以保故障隔离（R03 D-P1）：记忆索引损坏
可由 :meth:`sync` 扫盘重建，不牵动运行态事件溯源。

真源模型（design/06 §0）：**文件（md）为真源、SQLite 索引为派生投影**。``write()`` 把**浓缩文本**
原子追加到 memory root 下的 md（core→MEMORY.md、daily/distill→memory/<date>.md），再索进
``memory_chunks`` + FTS5；守 I3：只写浓缩文本、绝不写 delta。

关键词检索只有**两档**：FTS5 unicode61 → LIKE 兜底（CJK 靠 LIKE 命中）；**trigram-CJK 未实现、后置 P10**
（本仓 `memory_chunks_fts` 仅 `tokenize=unicode61`）。诚实边界（UNVERIFIED）：P4 无真 embedding（CI 无 key）
→ 向量列可为空、检索**降级关键词-only、不抛**（ADR-0026）；混合融合 / 时间衰减由 ``memory`` 子系统提供。
``aiosqlite`` 只在此 import（ruff banned-api 对 providers/* 豁免）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import aiosqlite

from questor.contracts.common import JsonObject, utc_now
from questor.contracts.memory import (
    EmbeddingPort,
    MemoryChunk,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryStorePort,
    MemoryStrategyConfig,
    MemoryWrite,
    MemoryWriteKind,
    VectorBackend,
    source_for_write,
)
from questor.memory.chunker import CHUNKER_VERSION
from questor.memory.search import decay_factor, fuse
from questor.memory.sync import build_chunks

#: 记忆库 DDL 版本；读到更高版本即 fail-closed（不猜测半升级表形，承 ADR-0022）。
MEMORY_SCHEMA_VERSION = 1

#: T8 阶段的兜底片段上限；T10 起由 ``MemoryStrategyConfig.snippet_max_bytes`` 覆盖。
_SNIPPET_MAX_BYTES = 2048

# 单一 schema authority、幂等 DDL。memory_chunks=派生索引；FTS5 独立内容表（手删手加）；
# embedding 以 JSON 文本存（NULL → 无向量、降级关键词）；write_ledger=claim-then-commit 幂等账。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_chunks (
    id         TEXT    PRIMARY KEY,
    scope      TEXT    NOT NULL,
    source     TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    hash       TEXT    NOT NULL,
    embedding  TEXT,
    metadata   TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    attributed_to TEXT
);
CREATE INDEX IF NOT EXISTS idx_mc_source ON memory_chunks (source, scope);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
    text, id UNINDEXED, path UNINDEXED, tokenize = 'unicode61'
);
CREATE TABLE IF NOT EXISTS write_ledger (
    idempotency_key TEXT    PRIMARY KEY,
    path            TEXT    NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    chunk_count     INTEGER NOT NULL,
    ts              TEXT    NOT NULL
);
"""


class MemorySchemaVersionError(ValueError):
    """记忆库 DDL 版本比本仓可解的更新；连接必须显式失败，绝不半重建（fail-closed）。"""


def _dumps(obj: object) -> str:
    """JSON 序列化：禁 NaN/Inf、紧凑、UTF-8 原样（承 store_sqlite 卫生，HARD C18）。"""
    return json.dumps(obj, allow_nan=False, separators=(",", ":"), ensure_ascii=False)


def _atomic_write_text(path: str, content: str) -> None:
    """临时文件 + ``os.replace`` 原子替换（ADR-0025：崩溃不留下半写文件）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".memtmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


class SQLiteVectorBackend(VectorBackend):
    """向量后端：embedding 以 JSON 文本存于 ``memory_chunks.embedding``，纯 Python cosine。

    不引入 numpy 依赖（CI 无该包）；无 embedding 的行被 :meth:`search` 跳过，触发上层关键词降级。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, chunk_id: str, embedding: tuple[float, ...]) -> None:
        await self._db.execute(
            "UPDATE memory_chunks SET embedding = ? WHERE id = ?", (_dumps(list(embedding)), chunk_id)
        )

    async def delete(self, chunk_ids: tuple[str, ...]) -> None:
        for cid in chunk_ids:
            await self._db.execute("UPDATE memory_chunks SET embedding = NULL WHERE id = ?", (cid,))

    async def search(self, query_embedding: tuple[float, ...], k: int) -> list[tuple[str, float]]:
        cur = await self._db.execute("SELECT id, embedding FROM memory_chunks WHERE embedding IS NOT NULL")
        scored: list[tuple[str, float]] = []
        for cid, blob in await cur.fetchall():
            vec = json.loads(blob)
            score = _cosine(query_embedding, vec)
            if score is not None:
                scored.append((cid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


def _cosine(a: tuple[float, ...] | list[float], b: list[float]) -> float | None:
    """纯 Python cosine；零范数返回 None（不可比，跳过该候选）。"""
    if len(a) != len(b) or not a:
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


class SQLiteMemoryStore(MemoryStorePort):
    """MemoryStorePort 的 SQLite 适配器（文件真源 + 派生索引）。用前先 ``await connect()``。"""

    def __init__(
        self,
        db_path: str = ":memory:",
        memory_root: str = "memory_store",
        config: MemoryStrategyConfig | None = None,
        embedder: EmbeddingPort | None = None,
    ) -> None:
        self.db_path = db_path
        self.memory_root = memory_root
        # 检索旋钮可插拔（DoD④）：换 config 即换融合/衰减行为，不动 kernel。
        self.config = config or MemoryStrategyConfig()
        # 向量生成器（B8；§20 C-3）：**只产向量**，入库仍走本 store 同一 `memory_chunks.embedding`
        # 列——不起第二 store、不起第二索引表。None = 无向量能力，检索自然降级关键词-only。
        self.embedder = embedder
        self._db: aiosqlite.Connection | None = None
        self.vector: SQLiteVectorBackend | None = None
        # 单连接事务不得跨协程交错（与事件 store 同理，track4 BLK-1）：--serve 多 run 共享本 store，
        # 并发 write/sync/write_memory_text 的 BEGIN→COMMIT 会互踩。此锁在 asyncio 层串行化全部 DB 入口。
        self._lock = asyncio.Lock()

    async def connect(self) -> SQLiteMemoryStore:
        # isolation_level=None → 自驱 BEGIN IMMEDIATE / COMMIT / ROLLBACK。
        os.makedirs(self.memory_root, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path, isolation_level=None)
        try:
            await self._db.execute("PRAGMA busy_timeout=30000")  # 跨进程瞬时争用下等锁而非立即抛错（#182）；不开 WAL（单写者由租约保证，避免 -wal 文件）。
            await self._db.executescript(_SCHEMA)
            await self._enforce_schema_version()
            await self._migrate_columns()
            self.vector = SQLiteVectorBackend(self._db)
        except BaseException:
            # schema 版本 fail-closed 等抛出时先关掉刚建的连接，避免 aiosqlite 非守护线程泄漏（#172）。
            await self._db.close()
            self._db = None
            raise
        return self

    async def _enforce_schema_version(self) -> None:
        assert self._db is not None
        cur = await self._db.execute("SELECT value FROM meta WHERE key = 'memory_schema_version'")
        row = await cur.fetchone()
        if row is None:
            await self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('memory_schema_version', ?)", (str(MEMORY_SCHEMA_VERSION),)
            )
            return
        stored = int(row[0])
        if stored > MEMORY_SCHEMA_VERSION:
            raise MemorySchemaVersionError(
                f"memory schema version {stored} is newer than this build can decode ({MEMORY_SCHEMA_VERSION}); refusing to half-read"
            )

    async def _migrate_columns(self) -> None:
        """幂等补列（B9）：旧库没有软删/过期/归因三列时补上，不重建库。

        这三列都在**派生索引**上（`memory.db` 可全量重建），真源始终是 md 文件；
        刻意**不建 `memory_history` 表**（§20 C-7：变更史 = 事件流）。
        """
        assert self._db is not None
        cur = await self._db.execute("PRAGMA table_info(memory_chunks)")
        existing = {row[1] for row in await cur.fetchall()}
        for column, ddl in (("is_deleted", "INTEGER NOT NULL DEFAULT 0"), ("expires_at", "TEXT"), ("attributed_to", "TEXT")):
            if column not in existing:
                await self._db.execute(f"ALTER TABLE memory_chunks ADD COLUMN {column} {ddl}")

    def _dbp(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteMemoryStore.connect() must be awaited before use")
        return self._db

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            self.vector = None

    async def write(self, write: MemoryWrite, *, idempotency_key: str) -> JsonObject:
        """把浓缩文本原子追加到真源 md 并索进派生索引（design/06 §0/§3；ADR-0025）。

        幂等：``write_ledger`` 命中同 ``idempotency_key`` → 直接返回原 receipt，不重复 append。
        返回 bounded receipt（path/start_line/end_line/chunk_count），**不含原文**。"""
        db = self._dbp()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT path, start_line, end_line, chunk_count FROM write_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = await cur.fetchone()
                if row is not None:
                    await db.execute("COMMIT")
                    return {"path": row[0], "start_line": row[1], "end_line": row[2], "chunk_count": row[3], "idempotent": True}
                rel, start, end, chunk = await asyncio.to_thread(self._append_to_source_file, write, idempotency_key)
                await self._index_chunk(chunk, embedding=await self._embed_one(chunk.text))
                await db.execute(
                    "INSERT INTO write_ledger (idempotency_key, path, start_line, end_line, chunk_count, ts) VALUES (?,?,?,?,?,?)",
                    (idempotency_key, rel, start, end, 1, utc_now().isoformat()),
                )
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise
            return {"path": rel, "start_line": start, "end_line": end, "chunk_count": 1, "idempotent": False}

    def _append_to_source_file(self, write: MemoryWrite, idempotency_key: str) -> tuple[str, int, int, MemoryChunk]:
        """原子追加一段浓缩文本到 md 文件，返回 (相对path, 起行, 止行, 派生 chunk)。

        幂等（#163B）：header 内嵌 ``<!-- idem:KEY -->``。若 marker 已在文件里，说明前一次 append
        已成功但 DB 事务回滚（write_ledger 无记录）——**不重复 append**，定位既有块行区间返回同一
        chunk。保证“文件每个 idempotency_key 恰好一块”，重投不产生二次正文。
        """
        date = utc_now().strftime("%Y-%m-%d")
        if write.kind is MemoryWriteKind.CORE:
            path = os.path.join(self.memory_root, "MEMORY.md")
        else:
            path = os.path.join(self.memory_root, "memory", f"{date}.md")
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                existing = fh.read()
        lines = existing.splitlines()
        rel = _rel(self.memory_root, path)
        source = source_for_write(write.kind)

        def _chunk(start: int, end: int) -> MemoryChunk:
            return MemoryChunk(
                id=hashlib.md5(f"{rel}:{start}:{end}:{write.text}".encode()).hexdigest(),
                scope=write.scope,
                source=source,
                path=rel,
                start_line=start,
                end_line=end,
                text=write.text.strip(),
                hash=hashlib.sha256(write.text.strip().encode()).hexdigest(),
                attributed_to=write.attributed_to,
                expires_at=write.expires_at,
            )

        marker = f"<!-- idem:{idempotency_key} -->"
        hit = next((i for i, ln in enumerate(lines) if marker in ln), None)
        if hit is not None:
            # 既有块（上次 append 成功但 DB 回滚）：不重复写；header 行 hit(0-based) → 1-based hit+1，
            # 止于下一个 `## ` header 前一行或文件末。
            start = hit + 1
            end = len(lines)
            for j in range(hit + 1, len(lines)):
                if lines[j].lstrip().startswith("## "):
                    end = j
                    break
            return rel, start, end, _chunk(start, end)

        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        # header 内嵌 scope（#163A）+ 幂等 marker（#163B）。
        header = f"{sep}\n## [{write.kind.value}] {utc_now().isoformat()} scope={write.scope.value} {marker}\n\n"
        new_content = existing + header + write.text.strip() + "\n"
        _atomic_write_text(path, new_content)
        start = len(lines) + 1
        end = len(new_content.splitlines())
        return rel, start, end, _chunk(start, end)

    async def _embed_one(self, text: str) -> tuple[float, ...] | None:
        """单条文本的向量；无 embedder / embedding 故障→ ``None``（降级关键词，不抛）。"""
        if self.embedder is None:
            return None
        try:
            vectors = await self.embedder.embed([text])
        except Exception:  # noqa: BLE001 - 向量后端不可用是合法降级（ADR-0026），不得拖垮记忆写
            return None
        return tuple(vectors[0]) if vectors else None

    async def _embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...] | None]:
        """批量 embedding（**一次调用处理 N 条**，不逐条往返）；失败返回全 None。"""
        if self.embedder is None or not texts:
            return [None] * len(texts)
        try:
            vectors = await self.embedder.embed(list(texts))
        except Exception:  # noqa: BLE001 - 同上：降级关键词-only
            return [None] * len(texts)
        return [tuple(vector) if vector is not None else None for vector in vectors] if len(vectors) == len(texts) else [None] * len(texts)

    async def _index_chunk(self, chunk: MemoryChunk, *, embedding: tuple[float, ...] | None) -> None:
        db = self._dbp()
        await db.execute(
            "INSERT OR REPLACE INTO memory_chunks (id, scope, source, path, start_line, end_line, text, hash, embedding, metadata,"
            " is_deleted, expires_at, attributed_to) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                chunk.id,
                chunk.scope.value,
                chunk.source.value,
                chunk.path,
                chunk.start_line,
                chunk.end_line,
                chunk.text,
                chunk.hash,
                _dumps(list(embedding)) if embedding is not None else None,
                _dumps(chunk.metadata) if chunk.metadata is not None else None,
                1 if chunk.is_deleted else 0,
                chunk.expires_at.isoformat() if chunk.expires_at is not None else None,
                chunk.attributed_to,
            ),
        )
        # FTS5 独立内容表：先删同 id 旧行再加，保持与 memory_chunks 一致（sync 亦重建）。
        await db.execute("DELETE FROM memory_chunks_fts WHERE id = ?", (chunk.id,))
        await db.execute(
            "INSERT INTO memory_chunks_fts (text, id, path) VALUES (?,?,?)", (chunk.text, chunk.id, chunk.path)
        )
        if embedding is not None and self.vector is not None:
            await self.vector.upsert(chunk.id, embedding)

    async def search(
        self,
        query: str,
        *,
        k: int,
        scope: MemoryScope | None = None,
        query_embedding: tuple[float, ...] | None = None,
    ) -> tuple[MemorySearchResult, ...]:
        """混合检索：关键词(FTS5/LIKE) + 向量(cosine) → rank-normalize 融合 → 时间衰减（ADR-0026）。

        无 ``query_embedding`` / 向量后端不可用 → 自然降级关键词-only（不抛）。片段按 config
        ``snippet_max_bytes`` 有界（HARD C18/ADR-0019）。融合/衰减纯函数住在 memory/search.py。"""
        cfg = self.config
        wide = max(k * 3, k)
        # 向量通道（B8）：调用方没传 query_embedding 且配了 embedder 时，现在算一个；
        # 算不出来就留 None——store.search 自己会降级关键词-only（不抛）。
        if query_embedding is None and self.embedder is not None:
            query_embedding = await self._embed_one(query)
        async with self._lock:
            keyword_ids, by_id = await self._keyword_candidates(query, scope=scope, limit=wide)
            vector_ids: list[str] = []
            if query_embedding is not None and self.vector is not None:
                for cid, _score in await self.vector.search(query_embedding, k=wide):
                    if cid not in by_id:
                        row = await self._fetch_chunk(cid)
                        if row is None or (scope is not None and row["scope"] != scope.value):
                            continue
                        by_id[cid] = row
                    elif scope is not None and by_id[cid]["scope"] != scope.value:
                        continue
                    vector_ids.append(cid)
            fused = fuse(keyword_ids, vector_ids, cfg)
        now = utc_now()
        results = [
            MemorySearchResult(
                path=by_id[cid]["path"],
                start_line=by_id[cid]["start_line"],
                end_line=by_id[cid]["end_line"],
                score=fused[cid] * decay_factor(by_id[cid]["path"], cfg, now),
                snippet=_bound_snippet(by_id[cid]["text"], max_bytes=cfg.snippet_max_bytes),
                source=MemorySource(by_id[cid]["source"]),
                scope=MemoryScope(by_id[cid]["scope"]),
                attributed_to=by_id[cid].get("attributed_to"),
            )
            for cid in fused
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return tuple(results[:k])

    async def _keyword_candidates(self, query: str, *, scope: MemoryScope | None, limit: int) -> tuple[list[str], dict[str, dict]]:
        """FTS5 unicode61 命中（best-first），空结果回退 LIKE；返回 (有序 id, id→行)。

        检索面永远只取未删未过期行（B9 纪律⑥/⑦）：软删位与硬过期都是行内事实，
        不靠“筛掉已返回结果”的下游补丁。
        """
        db = self._dbp()
        scope_sql = "AND mc.scope = ?" if scope is not None else ""
        # 绑定顺必须与 SQL 里的 ? 顺一致：query → expires → scope? → limit。
        params: tuple[Any, ...] = (query, utc_now().isoformat(), *([scope.value] if scope is not None else []), limit)
        try:
            cur = await db.execute(
                f"SELECT mc.id, mc.source, mc.scope, mc.path, mc.start_line, mc.end_line, mc.text, mc.attributed_to "
                f"FROM memory_chunks_fts f JOIN memory_chunks mc ON mc.id = f.id "
                f"WHERE memory_chunks_fts MATCH ? AND mc.is_deleted = 0 "
                f"AND (mc.expires_at IS NULL OR mc.expires_at > ?) {scope_sql} ORDER BY bm25(memory_chunks_fts) LIMIT ?",
                params,
            )
            rows = await cur.fetchall()
            if not rows:
                rows = await self._like_rows(query, scope=scope, limit=limit)
        except aiosqlite.OperationalError:
            rows = await self._like_rows(query, scope=scope, limit=limit)
        by_id: dict[str, dict] = {}
        ids: list[str] = []
        for r in rows:
            by_id[r[0]] = {
                "id": r[0],
                "source": r[1],
                "scope": r[2],
                "path": r[3],
                "start_line": r[4],
                "end_line": r[5],
                "text": r[6],
                "attributed_to": r[7] if len(r) > 7 else None,
            }
            ids.append(r[0])
        return ids, by_id

    async def _like_rows(self, query: str, *, scope: MemoryScope | None, limit: int) -> list:
        db = self._dbp()
        scope_sql = "AND scope = ?" if scope is not None else ""
        params: tuple[Any, ...] = (f"%{query}%", utc_now().isoformat(), *([scope.value] if scope is not None else []), limit)
        cur = await db.execute(
            f"SELECT id, source, scope, path, start_line, end_line, text, attributed_to FROM memory_chunks "
            f"WHERE text LIKE ? AND is_deleted = 0 AND (expires_at IS NULL OR expires_at > ?) {scope_sql} LIMIT ?",
            params,
        )
        return list(await cur.fetchall())

    async def _fetch_chunk(self, chunk_id: str) -> dict | None:
        cur = await self._dbp().execute(
            "SELECT id, source, scope, path, start_line, end_line, text, attributed_to, is_deleted, expires_at "
            "FROM memory_chunks WHERE id = ?",
            (chunk_id,),
        )
        r = await cur.fetchone()
        if r is None or r[8]:
            return None
        if r[9] is not None and str(r[9]) <= utc_now().isoformat():
            return None  # 硬过期不参与检索/排序（B9 纪律⑦）
        return {
            "id": r[0],
            "source": r[1],
            "scope": r[2],
            "path": r[3],
            "start_line": r[4],
            "end_line": r[5],
            "text": r[6],
            "attributed_to": r[7],
        }

    def _scan_source_files(self) -> dict[str, str]:
        """扫 memory root 下的 md 真源→ ``{相对path: 文本}``；跳过隐藏/临时文件（如 ``.memtmp_``）。"""
        files: dict[str, str] = {}
        for dirpath, _dirs, names in os.walk(self.memory_root):
            for name in names:
                if not name.endswith(".md") or name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                with open(full, encoding="utf-8") as fh:
                    files[_rel(self.memory_root, full)] = fh.read()
        return files

    async def sync(self) -> JsonObject:
        """扫盘 md（文件真源）→ chunker 重建派生索引 + reconcile stale 行（design/06 §0；ADR-0023）。

        全量 wipe+rebuild：先删 ``memory_chunks``/FTS，再按当前文件内容重建（``memory.sync.build_chunks``）。
        索引损坏或 ``CHUNKER_VERSION`` 变更都可由本函数自愈——文件永远权威；dreams 按映射排除不索。"""
        files = self._scan_source_files()
        chunks = build_chunks(files)
        # 全量 wipe+rebuild 不能把已撤回的记忆“滚回来”：先存住现有软删位，重建后重新标记。
        # 匹配用**行区间重叠**而不是精确等值：write 时的区间算的是“插入点”，chunker 重建时算的是
        # “markdown 节边界”（含节头行），两者本质上不会逐字相等；只比 hash 也会因节头入正文而失配。
        # 事件流仍是唯一权威（本集只是它的缓存），**不建第二表**。
        cur = await self._dbp().execute("SELECT path, start_line, end_line FROM memory_chunks WHERE is_deleted = 1")
        tombstones: dict[str, list[tuple[int, int]]] = {}
        for row in await cur.fetchall():
            tombstones.setdefault(str(row[0]), []).append((int(row[1]), int(row[2])))
        # 重建索引时只用**一次** embedding 调用处理 N 条（CrewAI EncodingFlow 的形状；
        # 逐条往返在千条级上就是时长炸弹）。
        embeddings = await self._embed_many([chunk.text for chunk in chunks])
        db = self._dbp()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute("DELETE FROM memory_chunks_fts")
                await db.execute("DELETE FROM memory_chunks")
                restored = 0
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    revoked = any(
                        chunk.start_line <= deleted_end and deleted_start <= chunk.end_line
                        for deleted_start, deleted_end in tombstones.get(chunk.path, ())
                    )
                    if revoked:
                        chunk = replace(chunk, is_deleted=True, embedding=None)
                        embedding = None
                        restored += 1
                    await self._index_chunk(chunk, embedding=embedding)
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise
        return {
            "reindexed": len(chunks),
            "files": len(files),
            "chunker_version": CHUNKER_VERSION,
            "revived": 0,
            "kept_deleted": restored,
        }

    async def delete(self, chunk_ids: tuple[str, ...]) -> None:
        db = self._dbp()
        async with self._lock:
            # 单事务包裹逐条删除：与模块头“BEGIN IMMEDIATE 串行单写者”一致，避免崩溃留半成品删除（#183）。
            await db.execute("BEGIN IMMEDIATE")
            try:
                for cid in chunk_ids:
                    await db.execute("DELETE FROM memory_chunks_fts WHERE id = ?", (cid,))
                    await db.execute("DELETE FROM memory_chunks WHERE id = ?", (cid,))
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise

    async def soft_delete(self, entry_id: str, *, idempotency_key: str) -> JsonObject:
        """按条目级 id 软删（B9 纪律⑥）：置 `is_deleted` + 从 FTS 摸掉，**不删真源、不建历史表**。

        幂等：同一 ``idempotency_key`` 命中 `write_ledger` 直接返回原 receipt；重复对同一
        条目软删也只会得到“命中 0 条”的如实结果，不会抛、不会回滚真源。
        """
        path, _, span = entry_id.partition(":")
        if not path or "-" not in span:
            raise ValueError(f"soft_delete needs a path:start-end entry_id, got {entry_id!r}")
        start_text, _, end_text = span.partition("-")
        try:
            start, end = int(start_text), int(end_text)
        except ValueError as exc:
            raise ValueError(f"soft_delete needs integer line bounds in {entry_id!r}") from exc
        db = self._dbp()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "SELECT path, start_line, end_line, chunk_count FROM write_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = await cur.fetchone()
                if row is not None:
                    await db.execute("COMMIT")
                    return {"entry_id": entry_id, "removed": 0, "idempotent": True}
                cur = await db.execute(
                    "SELECT id FROM memory_chunks WHERE path = ? AND start_line = ? AND end_line = ? AND is_deleted = 0",
                    (path, start, end),
                )
                doomed = [item[0] for item in await cur.fetchall()]
                for cid in doomed:
                    await db.execute("UPDATE memory_chunks SET is_deleted = 1, embedding = NULL WHERE id = ?", (cid,))
                    await db.execute("DELETE FROM memory_chunks_fts WHERE id = ?", (cid,))
                await db.execute(
                    "INSERT INTO write_ledger (idempotency_key, path, start_line, end_line, chunk_count, ts) VALUES (?,?,?,?,?,?)",
                    (idempotency_key, path, start, end, len(doomed), utc_now().isoformat()),
                )
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise
        return {"entry_id": entry_id, "removed": len(doomed), "idempotent": False}

    def _abs(self, rel_path: str) -> str:
        """将相对 memory root 的路径解为绝对；**拒绝越界**（path traversal / 符号链逃逸 fail-closed）。"""
        norm = os.path.normpath(rel_path).replace("\\", "/")
        if os.path.isabs(norm) or norm.startswith("..") or ".." in norm.split("/"):
            raise ValueError(f"memory path escapes root: {rel_path!r}")
        root_abs = os.path.abspath(self.memory_root)
        full = os.path.abspath(os.path.join(root_abs, norm))
        if os.path.commonpath([root_abs, full]) != root_abs:
            raise ValueError(f"memory path escapes root: {rel_path!r}")
        return full

    async def read_memory_text(self, rel_path: str) -> str:
        full = self._abs(rel_path)
        if not os.path.exists(full):
            return ""
        with open(full, encoding="utf-8") as fh:
            return fh.read()

    async def list_memory_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._scan_source_files()))

    async def list_entries(self, *, limit: int = 200, include_deleted: bool = False) -> list[JsonObject]:
        """列派生索引里的条目（B14 记忆管理面用）：**有界、零正文不截不猜**。

        只给面板渲染需要的字段：条目 id、路径/行区间、软删位、过期时刻、归因位与一段
        有界 snippet（复用 `_bound_snippet` + `config.snippet_max_bytes`，与检索侧同一口径）。
        默认不列已撤回项——
        用户删过的东西不该在“你的记忆”里重现，但 `include_deleted=True` 要能审计到（它仍在索引里）。
        本方法是**读投影**：真源本身是 md 文件，索引只是它的缓存。
        """
        sql = (
            "SELECT id, path, start_line, end_line, text, is_deleted, expires_at, attributed_to, source, scope "
            "FROM memory_chunks"
        )
        if not include_deleted:
            sql += " WHERE is_deleted = 0"
        sql += " ORDER BY path, start_line LIMIT ?"
        cur = await self._dbp().execute(sql, (max(0, int(limit)),))
        rows = await cur.fetchall()
        out: list[JsonObject] = []
        for row in rows:
            text = row[4] or ""
            out.append(
                {
                    # 对外一律用**条目级 id**（`path:start-end`）——与 citation / 消费打点 /
                    # `DeleteMemory` / `UpdateMemory` 同一形状；内部哈希主键另列一个键供调试。
                    "entry_id": f"{row[1]}:{row[2]}-{row[3]}",
                    "chunk_id": row[0],
                    "path": row[1],
                    "start_line": row[2],
                    "end_line": row[3],
                    "snippet": _bound_snippet(text, max_bytes=self.config.snippet_max_bytes),
                    "truncated": len(text.encode("utf-8")) > self.config.snippet_max_bytes,
                    "is_deleted": bool(row[5]),
                    "expires_at": row[6],
                    "attributed_to": row[7],
                    "source": row[8],
                    "scope": row[9],
                }
            )
        return out

    async def write_memory_text(self, rel_path: str, content: str, *, idempotency_key: str) -> JsonObject:
        """原子全量重写真源 md（Deep Dream 重写 core）；``idempotency_key`` 命中则 no-op。

        不自动索引；调用方随后 ``sync`` 从文件重建。越界路径 fail-closed（``_abs``）。"""
        full = self._abs(rel_path)
        db = self._dbp()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT path FROM write_ledger WHERE idempotency_key = ?", (idempotency_key,))
                if await cur.fetchone() is not None:
                    await db.execute("COMMIT")
                    return {"path": rel_path, "idempotent": True}
                _atomic_write_text(full, content)
                await db.execute(
                    "INSERT INTO write_ledger (idempotency_key, path, start_line, end_line, chunk_count, ts) VALUES (?,?,0,0,0,?)",
                    (idempotency_key, _rel(self.memory_root, full), utc_now().isoformat()),
                )
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise
        return {"path": rel_path, "idempotent": False}

    async def append_memory_text(self, rel_path: str, content: str, *, idempotency_key: str) -> JsonObject:
        """原子追加到真源 md（run-完成→daily flush、梦境日记）；幂等、只写浓缩不写 delta。

        不自动索引；调用方随后 ``sync`` 重建。越界 fail-closed。"""
        full = self._abs(rel_path)
        db = self._dbp()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute("SELECT path FROM write_ledger WHERE idempotency_key = ?", (idempotency_key,))
                if await cur.fetchone() is not None:
                    await db.execute("COMMIT")
                    return {"path": rel_path, "idempotent": True}
                existing = ""
                if os.path.exists(full):
                    with open(full, encoding="utf-8") as fh:
                        existing = fh.read()
                sep = "" if (not existing or existing.endswith("\n")) else "\n"
                _atomic_write_text(full, existing + sep + content)
                await db.execute(
                    "INSERT INTO write_ledger (idempotency_key, path, start_line, end_line, chunk_count, ts) VALUES (?,?,0,0,0,?)",
                    (idempotency_key, _rel(self.memory_root, full), utc_now().isoformat()),
                )
                await db.execute("COMMIT")
            except BaseException:
                await db.execute("ROLLBACK")
                raise
        return {"path": rel_path, "idempotent": False}


def _bound_snippet(text: str, *, max_bytes: int = _SNIPPET_MAX_BYTES) -> str:
    """有界片段：按 UTF-8 字节上限截断且不切断多字节字符（HARD C18/ADR-0019）。"""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    cut = data[:max_bytes]
    while cut and (cut[-1] & 0xC0) == 0x80:  # 去掉被截断的尾随字节
        cut = cut[:-1]
    return cut.decode("utf-8")
