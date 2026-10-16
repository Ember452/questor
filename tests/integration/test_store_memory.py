"""MemoryStorePort SQLite 适配器测（ADR-0023/0025/0026）：版本 fail-closed、写→检索命中、
幂等、CJK LIKE 兜底、片段有界。用 tmp_path 分别给 db 与 memory root（文件真源）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.memory import MemoryScope, MemorySource, MemoryWrite, MemoryWriteKind
from questor.providers.store_memory_sqlite import (
    MEMORY_SCHEMA_VERSION,
    MemorySchemaVersionError,
    SQLiteMemoryStore,
)


async def _open(tmp_path: Path) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore"))
    return await store.connect()


async def test_write_then_keyword_search_hits(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        receipt = await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="favorite id is MARINA77"),
            idempotency_key="w1",
        )
        assert receipt["chunk_count"] == 1
        hits = await store.search("MARINA77", k=5)
        assert hits, "keyword search must find the written fact"
        assert "MARINA77" in hits[0].snippet
        assert hits[0].source is MemorySource.DAILY
    finally:
        await store.close()


async def test_write_is_idempotent_by_key(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        r1 = await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.SESSION, text="alpha fact one"),
            idempotency_key="dup",
        )
        r2 = await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.SESSION, text="alpha fact one"),
            idempotency_key="dup",
        )
        assert r2["idempotent"] is True
        assert (r1["path"], r1["start_line"]) == (r2["path"], r2["start_line"])
        cur = await store._dbp().execute("SELECT COUNT(*) FROM memory_chunks")
        (n,) = await cur.fetchone()
        assert n == 1  # 重复 idempotency_key 不二次 append / 不二次索引（claim-then-commit）
    finally:
        await store.close()


async def test_cjk_falls_back_to_like(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.CORE, scope=MemoryScope.USER, text="用户偏好深蓝"),
            idempotency_key="c1",
        )
        hits = await store.search("深蓝", k=5)  # unicode61 不切 CJK → LIKE 兜底命中
        assert hits and "深蓝" in hits[0].snippet
    finally:
        await store.close()


async def test_snippet_is_bounded(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="needle " + "x" * 9000),
            idempotency_key="b1",
        )
        hits = await store.search("needle", k=5)
        assert hits
        assert len(hits[0].snippet.encode("utf-8")) <= 2048  # HARD C18/ADR-0019 有界
    finally:
        await store.close()


async def test_schema_version_fail_closed(tmp_path: Path) -> None:
    # 预置一个更高版本的 memory.db → 重新 connect 必须显式 fail-closed，绝不半读（承 ADR-0022 纪律）。
    store = await _open(tmp_path)  # 建库，meta=MEMORY_SCHEMA_VERSION
    await store._dbp().execute(
        "UPDATE meta SET value = ? WHERE key = 'memory_schema_version'",
        (str(MEMORY_SCHEMA_VERSION + 1),),
    )
    await store.close()
    reopened = SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore"))
    with pytest.raises(MemorySchemaVersionError):
        await reopened.connect()
