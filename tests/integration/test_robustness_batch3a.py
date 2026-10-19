"""批次3a 回归：#181 env 值级凭据、#183 delete 事务原子。（#179 因破坏"订阅先于起跑"契约已回退，另议）"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.providers.env_safety import scrub_environment
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


# ---- #181 -------------------------------------------------------------------
def test_proxy_value_with_embedded_userinfo_is_scrubbed() -> None:
    """名字安全（HTTP_PROXY）但值内嵌 user:pass@ 凭据 → 不透传；无凭据的代理值仍放行。"""
    env = {
        "PATH": "/usr/bin",
        "HTTP_PROXY": "http://alice:s3cr3t@proxy.corp:8080",
        "HTTPS_PROXY": "http://proxy.corp:8080",
    }
    kept, removed = scrub_environment(env)
    assert "HTTP_PROXY" not in kept and "HTTP_PROXY" in removed
    assert kept.get("HTTPS_PROXY") == "http://proxy.corp:8080"
    assert kept.get("PATH") == "/usr/bin"


# ---- #183 -------------------------------------------------------------------
async def test_memory_delete_rolls_back_on_mid_failure(tmp_path: Path) -> None:
    """delete 中途失败应整体回滚，memory_chunks 行不被半删。"""
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mr")).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="atomic delete probe body keeps here"),
            idempotency_key="dk1",
        )
        await store.sync()
        cur = await store._db.execute("SELECT id FROM memory_chunks LIMIT 1")
        row = await cur.fetchone()
        assert row is not None
        cid = row[0]
        real = store._db.execute

        async def flaky(sql, params=()):  # 注入：删非 fts 表那一步失败
            if sql.strip().startswith("DELETE FROM memory_chunks WHERE"):
                raise RuntimeError("injected delete failure")
            return await real(sql, params)

        store._db.execute = flaky  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await store.delete((cid,))
        store._db.execute = real  # type: ignore[method-assign]
        cur2 = await store._db.execute("SELECT count(*) FROM memory_chunks WHERE id = ?", (cid,))
        assert (await cur2.fetchone())[0] == 1, "回滚失败：memory_chunks 行被删"
    finally:
        await store.close()
