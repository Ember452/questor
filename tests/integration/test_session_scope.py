"""B4 会话作用域：sessions 行 + event_log.scope/session_id 迁移与绑定（v3 §4.5）。"""

from __future__ import annotations

import aiosqlite
import pytest

from questor.contracts.state_schema import RunStatus
from questor.kernel.recovery import rebuild_run
from questor.kernel.seed import SeedRef, SeedRejected, build_seed_context
from questor.providers.fake import EchoProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer


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


async def test_list_unfinished_runs_excludes_session_stream(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "list.db")).connect()
    try:
        await store.append("run-open", ({"type": "run_started", "data": {}},))
        await store.append("sess:s1", ({"type": "memory_written", "data": {}},))
        assert await store.list_unfinished_runs() == ("run-open",)  # 会话流不混入 --list
    finally:
        await store.close()


async def test_seed_context_marker_and_original_text(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "seed.db")).connect()
    try:
        sid = await store.create_session("s1")
        await store.bind_run_session("run-1", sid)
        await store.append("run-1", ({"type": "user_message", "data": {"text": "remember ZEPHYR-9"}},))
        await store.append("run-1", ({"type": "message_completed", "data": {"final_text": "noted ZEPHYR-9"}},))
        message = await build_seed_context(store, sid)
        marker = message.content[0]
        assert marker.type == "system_marker" and marker.payload["origin"] == "seed"
        assert "ZEPHYR-9" in message.content[1].text
        assert "remember" in message.content[1].text
    finally:
        await store.close()


async def test_seed_three_rejections(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "seed-reject.db")).connect()
    try:
        with pytest.raises(SeedRejected) as busy:
            await build_seed_context(store, "s1", status=RunStatus.RUNNING)
        assert busy.value.reason == "idle_only"

        with pytest.raises(SeedRejected) as cross:
            await build_seed_context(store, "s1", refs=(SeedRef("other", 1),))
        assert cross.value.reason == "cross_session"

        with pytest.raises(SeedRejected) as oversize:
            await build_seed_context(store, "s1", refs=tuple(SeedRef("s1", i) for i in range(33)))
        assert oversize.value.reason == "oversize"
    finally:
        await store.close()


def _seed_marker(run) -> bool:  # noqa: ANN001
    return any(
        block.type == "system_marker" and block.payload and block.payload.get("origin") == "seed"
        for message in run.context.items
        for block in message.content
    )


async def test_start_run_session_seed_and_new_session(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "http-session.db")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider())
        server = EventServer(surface, store)
        first_id = await server.start_run("first", session_id="s-http")
        await store_task(server, first_id)
        second_id = await server.start_run("second", session_id="s-http")
        await store_task(server, second_id)
        second = await rebuild_run(store, second_id)
        assert second is not None and _seed_marker(second)
        seed_text = "".join(b.text or "" for b in second.context.items[0].content if b.type == "text")
        assert "echo" in seed_text

        third_id = await server.start_run("third")
        await store_task(server, third_id)
        third = await rebuild_run(store, third_id)
        assert third is not None and not _seed_marker(third)
        sid = await store.run_session(third_id)
        assert sid is not None and await store.session_row(sid) is not None
    finally:
        await store.close()


async def test_run_once_session_seed_and_new_session(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "cli-session.db")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider())
        await surface.run_once("one", session_id="s-cli")
        second = await surface.run_once("two", session_id="s-cli")
        assert _seed_marker(second)
        seed_text = "".join(b.text or "" for b in second.context.items[0].content if b.type == "text")
        assert "echo" in seed_text

        third = await surface.run_once("three")
        assert not _seed_marker(third)
        sid = await store.run_session(third.run_id)
        assert sid is not None and await store.session_row(sid) is not None
    finally:
        await store.close()


async def store_task(server: EventServer, run_id: str) -> None:
    """等 EventServer 的后台驱动任务落终态（测试辅助）。"""
    active = server.registry._runs.get(run_id)  # noqa: SLF001 - 测试观察点
    assert active is not None and active.task is not None
    await active.task
