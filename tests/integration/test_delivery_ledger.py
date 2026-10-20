"""B11 交付账本：扩列/五态/三 sweep/裁剪 + 触发只经 submissions（v3 §8/§9）。"""

from __future__ import annotations

import aiosqlite

from questor.providers.store_sqlite import SQLiteStore


async def test_old_v3_deliveries_migrate_and_obligation_is_idempotent(tmp_path) -> None:
    path = str(tmp_path / "old.db")
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, state TEXT NOT NULL, claimed_at REAL NOT NULL, ttl_seconds REAL NOT NULL);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('store_schema_version', '3');
            INSERT INTO deliveries (delivery_id, state, claimed_at, ttl_seconds) VALUES ('old', 'claimed', 1.0, 30.0);
            """
        )
        await db.commit()

    store = await SQLiteStore(path).connect()
    try:
        cur = await store._dbp().execute("PRAGMA table_info(deliveries)")  # noqa: SLF001
        columns = {row[1] for row in await cur.fetchall()}
        assert {"obligation_id", "owner_pid", "owner_start", "attempts", "not_before", "recovered", "platform"} <= columns
        old = await store.delivery_row("old")
        assert old is not None and old["state"] == "claimed" and old["attempts"] == 0

        assert await store.create_obligation("d1", "sha-1", "desktop", session_id="s1", content_sha="abc") is True
        assert await store.create_obligation("d1", "sha-1", "desktop", session_id="s1", content_sha="abc") is True
        assert await store.create_obligation("d1", "sha-2", "desktop") is False  # 同 id 异义务不覆盖
        row = await store.delivery_row("d1")
        assert row is not None and row["state"] == "pending" and row["obligation_id"] == "sha-1"
        assert await store.create_obligation("d2", "sha-2", "im") is True
        assert (await store.delivery_row("d2"))["state"] == "undeliverable"
    finally:
        await store.close()


async def test_legacy_claim_and_ack_semantics_stay(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "legacy.db")).connect()
    try:
        assert await store.claim_delivery("legacy", ttl_seconds=100) is True
        assert await store.delivery_state("legacy") == "claimed"
        assert await store.ack_delivery("legacy") is True
        assert await store.delivery_state("legacy") == "acked"
    finally:
        await store.close()
