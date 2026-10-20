"""B4 会话作用域：sessions 行 + event_log.scope/session_id 迁移与绑定（v3 §4.5）。"""

from __future__ import annotations

import aiosqlite

from questor.providers.store_sqlite import SQLiteStore


async def test_old_v2_store_migrates_session_columns(tmp_path) -> None:
    path = str(tmp_path / "old.db")
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE event_log (
                gseq INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL,
                turn INTEGER, item_id TEXT, payload TEXT NOT NULL, ts TEXT NOT NULL,
                UNIQUE (run_id, seq)
            );
            CREATE TABLE runs (run_id TEXT PRIMARY KEY, head_seq INTEGER NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('store_schema_version', '2');
            INSERT INTO event_log (run_id, seq, type, payload, ts) VALUES ('run-old', 1, 'run_started', '{}', '2026-01-01T00:00:00+00:00');
            """
        )
        await db.commit()

    store = await SQLiteStore(path).connect()
    try:
        cur = await store._dbp().execute("PRAGMA table_info(event_log)")  # noqa: SLF001 - migration assertion
        columns = {row[1] for row in await cur.fetchall()}
        assert {"session_id", "scope"} <= columns
        cur = await store._dbp().execute("PRAGMA table_info(runs)")  # noqa: SLF001
        assert "session_id" in {row[1] for row in await cur.fetchall()}
        cur = await store._dbp().execute("SELECT value FROM meta WHERE key = 'store_schema_version'")
        assert (await cur.fetchone())[0] == "3"
        old = await store.replay("run-old", 0)
        assert old[0]["data"] == {}  # 旧事件仍可读
    finally:
        await store.close()


async def test_session_row_and_double_cursor(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "sessions.db")).connect()
    try:
        sid = await store.create_session("sess-explicit", model="echo", workspace_root=str(tmp_path))
        assert sid == "sess-explicit"
        row = await store.session_row(sid)
        assert row is not None and row["model"] == "echo" and row["last_consolidated"] == 0
        assert (await store.ensure_session(sid))["session_id"] == sid
        assert await store.advance_last_consolidated(sid, 7) == 1
        assert await store.advance_last_consolidated(sid, 3) == 1
        assert (await store.session_row(sid))["last_consolidated"] == 7  # 只前进
        assert await store.set_history_start_seq(sid, 5) == 1
        assert (await store.session_row(sid))["history_start_seq"] == 5
    finally:
        await store.close()


async def test_append_derives_scope_and_session_id(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "scope.db")).connect()
    try:
        sid = await store.create_session("s1")
        await store.bind_run_session("run-1", sid)
        await store.append("run-1", ({"type": "run_started", "data": {"run_id": "run-1"}},))
        assert await store.run_session("run-1") == sid

        await store.append("sess:s1", ({"type": "memory_written", "seq": 1, "data": {"kind": "daily"}},))
        rows = await store.session_events(sid)
        assert [(row["run_id"], row["scope"]) for row in rows] == [("run-1", "run"), ("sess:s1", "session")]
        assert all(row["session_id"] == sid for row in rows)
        assert await store.replay("run-1", 0) == [
            {"gseq": 1, "seq": 1, "type": "run_started", "turn": None, "item_id": None, "data": {"run_id": "run-1"}, "ts": rows[0]["ts"]}
        ]
    finally:
        await store.close()
