"""记忆 sync 重建测（文件真源、索引派生；ADR-0023/design/06 §0）。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


async def _open(tmp_path: Path) -> SQLiteMemoryStore:
    return await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore")).connect()


async def test_sync_rebuilds_canonical_index_and_excludes_dreams(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="favorite id is MARINA77"),
            idempotency_key="w1",
        )
        dreams_dir = tmp_path / "mstore" / "memory" / "dreams"
        dreams_dir.mkdir(parents=True, exist_ok=True)
        (dreams_dir / "2026-10-16.md").write_text("# dream\nDREAMONLY-99 marker\n", encoding="utf-8")

        stats = await store.sync()
        assert stats["reindexed"] >= 1
        assert (await store.search("MARINA77", k=5)) != ()  # daily 文件重建后仍可检索
        assert await store.search("DREAMONLY-99", k=5) == ()  # dreams 不进检索索引（design/06 §1）

        # sync 幂等：文件未变则二次重建 chunk 数一致（派生投影可重复重建）。
        assert (await store.sync())["reindexed"] == stats["reindexed"]
    finally:
        await store.close()
