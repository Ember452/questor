"""MemoryStorePort SQLite 适配器测（ADR-0023/0025/0026）：版本 fail-closed、写→检索命中、
幂等、CJK LIKE 兜底、片段有界。用 tmp_path 分别给 db 与 memory root（文件真源）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.memory import MemoryScope, MemorySource, MemoryStrategyConfig, MemoryWrite, MemoryWriteKind
from questor.providers.store_memory_sqlite import (
    MEMORY_SCHEMA_VERSION,
    MemorySchemaVersionError,
    SQLiteMemoryStore,
)


async def _open(tmp_path: Path) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore"))
    return await store.connect()


async def test_write_after_ledger_rollback_does_not_double_append(tmp_path: Path) -> None:
    """#163(B)：文件已 append、DB 事务回滚后同 key 重投，不得二次 append（幂等 marker 兼补偿）。"""
    from questor.contracts.common import utc_now

    store = await _open(tmp_path)
    try:
        w = MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="idempotent body ZZZ")
        await store.write(w, idempotency_key="kx")
        # 模拟“文件写了但 DB 回滚”：删掉幂等账（write_ledger），但文件仍在。
        await store._db.execute("DELETE FROM write_ledger WHERE idempotency_key = 'kx'")
        await store._db.commit()
        await store.write(w, idempotency_key="kx")  # marker 命中 → 不二次 append
        date = utc_now().strftime("%Y-%m-%d")
        content = (tmp_path / "mstore" / "memory" / f"{date}.md").read_text(encoding="utf-8")
        assert content.count("idempotent body ZZZ") == 1, f"重投二次 append：{content.count('idempotent body ZZZ')} 次"
    finally:
        await store.close()


async def test_sync_preserves_shared_scope(tmp_path: Path) -> None:
    """#163(A)：sync 全量重建必须按节头恢复 scope，不把 SHARED 蒸馏块误抹为 USER。"""
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DISTILL, scope=MemoryScope.SHARED, text="shared distill marker fact AAA", covered_from=0, covered_to=1, covered_hash="deadbeef"),
            idempotency_key="distill:1",
        )
        await store.sync()  # 重建索引（旧实现会把 scope 抹为 USER）
        shared = await store.search("shared distill marker fact AAA", k=5, scope=MemoryScope.SHARED)
        user = await store.search("shared distill marker fact AAA", k=5, scope=MemoryScope.USER)
        assert any("AAA" in r.snippet for r in shared), f"sync 后 SHARED scope 丢失：{[r.snippet for r in shared]}"
        assert not any("AAA" in r.snippet for r in user), "SHARED 块被误标为 USER（scope 隔离失效）"
    finally:
        await store.close()


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


async def test_search_degrades_to_keyword_without_embedding(tmp_path: Path) -> None:
    # 向量后端无 embedding（写时 embedding=None）→ 带 query_embedding 检索也不抛，降级关键词命中（ADR-0026）。
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="alpha one fact"),
            idempotency_key="e1",
        )
        hits = await store.search("alpha", k=5, query_embedding=(0.1, 0.2, 0.3))
        assert hits and "alpha" in hits[0].snippet
    finally:
        await store.close()


async def test_pluggable_configs_both_retrieve(tmp_path: Path) -> None:
    # DoD④：默认 vs 替换策略（不同融合权重/半衰期）跑同一写入均命中，无需改 kernel。
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="the secret token is GLYPH7"),
            idempotency_key="s1",
        )
        store.config = MemoryStrategyConfig(vector_weight=0.9, keyword_weight=0.1)
        vec_heavy = await store.search("GLYPH7", k=5)
        store.config = MemoryStrategyConfig(vector_weight=0.1, keyword_weight=0.9, half_life_days=7.0)
        kw_heavy = await store.search("GLYPH7", k=5)
        assert vec_heavy and kw_heavy
        assert "GLYPH7" in vec_heavy[0].snippet and "GLYPH7" in kw_heavy[0].snippet
    finally:
        await store.close()
