"""L5 MemoryStorePort -> SQLite（独立 ``memory.db``；ADR-0023/0025/0026）。

按 P3 :mod:`questor.providers.store_sqlite` 验证过的纪律自写：单一 ``_SCHEMA`` authority +
幂等 DDL（``IF NOT EXISTS``）+ ``meta(memory_schema_version)`` 未知更新版本 fail-closed +
``BEGIN IMMEDIATE`` 串行单写者。与 event-log **分库**以保故障隔离（R03 D-P1）：记忆索引损坏
可由 :meth:`sync` 扫盘重建，不牵动运行态事件溯源。

真源模型（design/06 §0）：**文件（md）为真源、SQLite 索引为派生投影**。``write()`` 把**浓缩文本**
原子追加到 memory root 下的 md（core→MEMORY.md、daily/distill→memory/<date>.md），再索进
``memory_chunks`` + FTS5；守 I3：只写浓缩文本、绝不写 delta。

诚实边界（UNVERIFIED）：P4 无真 embedding（CI 无 key）→ 向量列可为空、检索**降级关键词-only、
不抛**（ADR-0026）。混合融合 / 时间衰减 / trigram-CJK 由 ``memory`` 子系统在 T9/T10 精化，本适配器
先落存储骨架 + 幂等写 + 关键词查询。``aiosqlite`` 只在此 import（ruff banned-api 对 providers/* 豁免）。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any

import aiosqlite

from questor.contracts.common import JsonObject, utc_now
from questor.contracts.memory import (
    MemoryChunk,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryStorePort,
    MemoryWrite,
    MemoryWriteKind,
    VectorBackend,
)

#: 记忆库 DDL 版本；读到更高版本即 fail-closed（不猜测半升级表形，承 ADR-0022）。
MEMORY_SCHEMA_VERSION = 1

#: T8 阶段的兜底片段上限；T10 起由 ``MemoryStrategyConfig.snippet_max_bytes`` 覆盖。
_SNIPPET_MAX_BYTES = 2048

#: 写 kind → 记忆 source 层（distill 浓缩固化进 daily 检索层，design/06 §3）。
_KIND_TO_SOURCE: dict[MemoryWriteKind, MemorySource] = {
    MemoryWriteKind.CORE: MemorySource.CORE,
    MemoryWriteKind.DAILY: MemorySource.DAILY,
    MemoryWriteKind.DISTILL: MemorySource.DAILY,
}

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
    metadata   TEXT
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

    def __init__(self, db_path: str = ":memory:", memory_root: str = "memory_store") -> None:
        self.db_path = db_path
        self.memory_root = memory_root
        self._db: aiosqlite.Connection | None = None
        self.vector: SQLiteVectorBackend | None = None

    async def connect(self) -> SQLiteMemoryStore:
        # isolation_level=None → 自驱 BEGIN IMMEDIATE / COMMIT / ROLLBACK。
        os.makedirs(self.memory_root, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path, isolation_level=None)
        await self._db.executescript(_SCHEMA)
        await self._enforce_schema_version()
        self.vector = SQLiteVectorBackend(self._db)
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
            rel, start, end, chunk = self._append_to_source_file(write)
            await self._index_chunk(chunk, embedding=None)
            await db.execute(
                "INSERT INTO write_ledger (idempotency_key, path, start_line, end_line, chunk_count, ts) VALUES (?,?,?,?,?,?)",
                (idempotency_key, rel, start, end, 1, utc_now().isoformat()),
            )
            await db.execute("COMMIT")
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        return {"path": rel, "start_line": start, "end_line": end, "chunk_count": 1, "idempotent": False}

    def _append_to_source_file(self, write: MemoryWrite) -> tuple[str, int, int, MemoryChunk]:
        """原子追加一段浓缩文本到 md 文件，返回 (相对path, 起行, 止行, 派生 chunk)。"""
        date = utc_now().strftime("%Y-%m-%d")
        if write.kind is MemoryWriteKind.CORE:
            path = os.path.join(self.memory_root, "MEMORY.md")
        else:
            path = os.path.join(self.memory_root, "memory", f"{date}.md")
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                existing = fh.read()
        prior_lines = existing.splitlines()
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        header = f"{sep}\n## [{write.kind.value}] {utc_now().isoformat()}\n\n"
        body = header + write.text.strip() + "\n"
        new_content = existing + body
        _atomic_write_text(path, new_content)
        new_lines = new_content.splitlines()
        start = len(prior_lines) + 1
        end = len(new_lines)
        rel = _rel(self.memory_root, path)
        source = _KIND_TO_SOURCE[write.kind]
        chunk = MemoryChunk(
            id=hashlib.md5(f"{rel}:{start}:{end}:{write.text}".encode()).hexdigest(),
            scope=write.scope,
            source=source,
            path=rel,
            start_line=start,
            end_line=end,
            text=write.text.strip(),
            hash=hashlib.sha256(write.text.strip().encode()).hexdigest(),
        )
        return rel, start, end, chunk

    async def _index_chunk(self, chunk: MemoryChunk, *, embedding: tuple[float, ...] | None) -> None:
        db = self._dbp()
        await db.execute(
            "INSERT OR REPLACE INTO memory_chunks (id, scope, source, path, start_line, end_line, text, hash, embedding, metadata) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
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
        """T8：关键词 FTS5（unicode61），非法/空查询回退 LIKE。向量+融合+时间衰减由 memory 子系统在 T10 叠加。"""
        db = self._dbp()
        scope_sql = "AND mc.scope = ?" if scope is not None else ""
        params: tuple[Any, ...] = (query,) if scope is None else (query, scope.value)
        try:
            cur = await db.execute(
                f"SELECT mc.id, mc.source, mc.scope, mc.path, mc.start_line, mc.end_line, mc.text "
                f"FROM memory_chunks_fts f JOIN memory_chunks mc ON mc.id = f.id "
                f"WHERE memory_chunks_fts MATCH ? {scope_sql} LIMIT ?",
                (*params, k),
            )
            rows = await cur.fetchall()
            if not rows and query_embedding is None:
                # unicode61 未命中（如纯 CJK）→ LIKE 兜底（trigram-CJK 精化后置 T10）。
                rows = await self._like_fallback(query, k=k, scope=scope)
        except aiosqlite.OperationalError:
            rows = await self._like_fallback(query, k=k, scope=scope)
        results: list[MemorySearchResult] = []
        for i, r in enumerate(rows):
            results.append(
                MemorySearchResult(
                    path=r[3],
                    start_line=r[4],
                    end_line=r[5],
                    score=1.0 / (i + 1),  # T8 名次占位分；T10 rank-normalize 融合替换
                    snippet=_bound_snippet(r[6]),
                    source=MemorySource(r[1]),
                    scope=MemoryScope(r[2]),
                )
            )
        return tuple(results)

    async def _like_fallback(self, query: str, *, k: int, scope: MemoryScope | None) -> list:
        db = self._dbp()
        scope_sql = "AND scope = ?" if scope is not None else ""
        params: tuple[Any, ...] = (f"%{query}%", k) if scope is None else (f"%{query}%", scope.value, k)
        cur = await db.execute(
            f"SELECT id, source, scope, path, start_line, end_line, text FROM memory_chunks "
            f"WHERE text LIKE ? {scope_sql} LIMIT ?",
            params,
        )
        return list(await cur.fetchall())

    async def sync(self) -> JsonObject:
        """重建派生索引（扫盘 md → 逐块重索）并 reconcile stale 行。

        T8 最小实现：清空索引表后按 ``memory_chunks`` 现存文本重建 FTS；真正的扫盘 markdown
        感知重建由 ``memory`` 子系统的 chunker 在 T9 接管（文件为真源，索引损坏可重建）。"""
        db = self._dbp()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute("DELETE FROM memory_chunks_fts")
            cur = await db.execute("SELECT id, text, path FROM memory_chunks")
            for cid, text, path in await cur.fetchall():
                await db.execute("INSERT INTO memory_chunks_fts (text, id, path) VALUES (?,?,?)", (text, cid, path))
            await db.execute("COMMIT")
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        return {"reindexed": True}

    async def delete(self, chunk_ids: tuple[str, ...]) -> None:
        db = self._dbp()
        for cid in chunk_ids:
            await db.execute("DELETE FROM memory_chunks_fts WHERE id = ?", (cid,))
            await db.execute("DELETE FROM memory_chunks WHERE id = ?", (cid,))


def _bound_snippet(text: str, *, max_bytes: int = _SNIPPET_MAX_BYTES) -> str:
    """有界片段：按 UTF-8 字节上限截断且不切断多字节字符（HARD C18/ADR-0019）。"""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    cut = data[:max_bytes]
    while cut and (cut[-1] & 0xC0) == 0x80:  # 去掉被截断的尾随字节
        cut = cut[:-1]
    return cut.decode("utf-8")
