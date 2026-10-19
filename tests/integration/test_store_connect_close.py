"""#172：store connect() 在 schema 版本 fail-closed 抛出时必须关掉刚建的连接（防非守护线程泄漏）。"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from questor.providers.store_memory_sqlite import (
    MEMORY_SCHEMA_VERSION,
    MemorySchemaVersionError,
    SQLiteMemoryStore,
)
from questor.providers.store_sqlite import (
    STORE_SCHEMA_VERSION,
    SQLiteStore,
    StoreSchemaVersionError,
)


async def test_event_store_connect_closes_on_schema_version_error(tmp_path: Path) -> None:
    path = str(tmp_path / "s.db")
    store = await SQLiteStore(path).connect()
    await store.close()
    # 把存的版本抬到比本构建更新 → 再 connect 触发 fail-closed。
    raw = await aiosqlite.connect(path, isolation_level=None)
    await raw.execute("UPDATE meta SET value=? WHERE key='store_schema_version'", (str(STORE_SCHEMA_VERSION + 1),))
    await raw.commit()
    await raw.close()

    fresh = SQLiteStore(path)
    with pytest.raises(StoreSchemaVersionError):
        await fresh.connect()
    assert fresh._db is None, "抛出后连接未关闭 → aiosqlite 非守护线程泄漏"


async def test_memory_store_connect_closes_on_schema_version_error(tmp_path: Path) -> None:
    db_path = str(tmp_path / "m.db")
    root = str(tmp_path / "mr")
    store = await SQLiteMemoryStore(db_path=db_path, memory_root=root).connect()
    await store.close()
    raw = await aiosqlite.connect(db_path, isolation_level=None)
    await raw.execute("UPDATE meta SET value=? WHERE key='memory_schema_version'", (str(MEMORY_SCHEMA_VERSION + 1),))
    await raw.commit()
    await raw.close()

    fresh = SQLiteMemoryStore(db_path=db_path, memory_root=root)
    with pytest.raises(MemorySchemaVersionError):
        await fresh.connect()
    assert fresh._db is None, "抛出后连接未关闭 → aiosqlite 非守护线程泄漏"
