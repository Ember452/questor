"""B14 记忆管理面（可见可改）：`GET /memory` 与 `PATCH /memory`。

验收口径是 §13 B14 那一句：**改/删之后，下次召回不含旧值**——所以这里的判据不是"接口返回 200"，
而是"检索面真的不再命中"，同时事实流多了一条 `memory_updated`/`memory_deleted` 而**没有**多一条
`memory_written`（编辑对用户是一个事实，退役+重写是它的实现细节）。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.providers.fake import EchoProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app

_OLD = "the vendor is ACME-CORP-77"
_NEW = "the vendor is GLOBEX-CORP-88"


async def _setup(tmp_path: Path) -> tuple[SQLiteStore, SQLiteMemoryStore, httpx.AsyncClient]:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    await memory.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=_OLD, attributed_to="user"),
        idempotency_key="seed-1",
    )
    surface = CliSurface(workspace_root=tmp_path, store=store, memory_store=memory, provider=EchoProvider())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(EventServer(surface, store))), base_url="http://svc", timeout=30, trust_env=False
    )
    return store, memory, client


async def test_memory_list_is_bounded_and_uses_entry_ids(tmp_path: Path) -> None:
    store, memory, client = await _setup(tmp_path)
    try:
        body = (await client.get("/memory")).json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        # 条目级 id：与 citation / 消费打点 / DeleteMemory 同一形状，前端不需要内部哈希主键
        assert item["entry_id"].count(":") >= 1 and item["entry_id"].split(":")[-1].count("-") == 1
        assert item["is_deleted"] is False and item["attributed_to"] == "user"
        assert _OLD in item["snippet"]
        assert (await client.get("/memory", params={"limit": 0})).status_code == 400
        assert (await client.get("/memory", params={"limit": 2, "include_deleted": "true"})).status_code == 200
    finally:
        await client.aclose()
        await memory.close()
        await store.close()


async def test_patch_memory_edit_removes_the_old_value_from_recall(tmp_path: Path) -> None:
    """改一条记忆：旧值不再被召回、新值可以；事实流多一条 `memory_updated`，**不多一条写入**。"""
    store, memory, client = await _setup(tmp_path)
    try:
        entry_id = (await client.get("/memory")).json()["items"][0]["entry_id"]
        res = await client.patch("/memory", json={"entry_id": entry_id, "text": _NEW, "reason": "vendor changed"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["events"] == ["memory_updated"]
        assert body["superseded"] == 1 and body["wrote"] is True

        assert await memory.search("ACME-CORP-77", k=5) == ()  # 旧值退出了检索（不是排序靠后）
        hits = await memory.search("GLOBEX-CORP-88", k=5)
        assert hits and "GLOBEX-CORP-88" in hits[0].snippet

        rows = await store.replay(f"sess:mem:{entry_id}", 0)
        assert [r["type"] for r in rows] == ["memory_updated"]
        # 真源 md 没被就地改写：编辑是"退役 + 追加替代"，文件仍是 append-only 事实的载体
        paths = await memory.list_memory_paths()
        daily = next(path for path in paths if path.startswith("memory/"))
        text = await memory.read_memory_text(daily)
        assert _OLD in text and _NEW in text
    finally:
        await client.aclose()
        await memory.close()
        await store.close()


async def test_patch_memory_delete_revokes_and_is_replayable(tmp_path: Path) -> None:
    """删一条记忆：durable `memory_deleted` + 软删位；列表默认不再显示它，审计模式仍在。"""
    store, memory, client = await _setup(tmp_path)
    try:
        entry_id = (await client.get("/memory")).json()["items"][0]["entry_id"]
        res = await client.patch("/memory", json={"entry_id": entry_id, "delete": True, "reason": "wrong"})
        assert res.status_code == 200, res.text
        assert res.json()["events"] == ["memory_deleted"]
        assert await memory.search("ACME-CORP-77", k=5) == ()
        assert (await client.get("/memory")).json()["items"] == []
        audit = (await client.get("/memory", params={"include_deleted": "true"})).json()["items"]
        assert len(audit) == 1 and audit[0]["is_deleted"] is True
        rows = await store.replay(f"sess:mem:{entry_id}", 0)
        assert [r["type"] for r in rows] == ["memory_deleted"]
        # 撤回史只有事件流一份：没有第二张历史表（§20 C-7）。直查 sqlite_master，而不是靠“没报错”推定。
        cur = await memory._db.execute("SELECT name FROM sqlite_master WHERE type='table'")  # type: ignore[union-attr]
        tables = {row[0] for row in await cur.fetchall()}
        assert "memory_history" not in tables
        assert "memory_chunks" in tables  # 仍然只那一张派生索引表
    finally:
        await client.aclose()
        await memory.close()
        await store.close()


async def test_memory_patch_validates_without_writing(tmp_path: Path) -> None:
    store, memory, client = await _setup(tmp_path)
    try:
        entry_id = (await client.get("/memory")).json()["items"][0]["entry_id"]
        assert (await client.patch("/memory", json={"entry_id": "no-colon", "text": "x"})).status_code == 400
        assert (await client.patch("/memory", json={"entry_id": entry_id})).status_code == 400  # 既不给文本也不删
        assert (await client.patch("/memory", json={"entry_id": entry_id, "text": "   "})).status_code == 400
        assert (await client.patch("/memory", json={"entry_id": entry_id, "delete": "yes"})).status_code == 400
        assert (await client.patch("/memory", json={"entry_id": entry_id, "text": "x", "model": "gpt"})).status_code == 400
        # 被拒的请求不得留下任何记忆事实，也不得改动条目
        for stream in (f"sess:mem:{entry_id}",):
            assert await store.replay(stream, 0) == []
        assert await memory.search("ACME-CORP-77", k=5)  # 原条目仍在
    finally:
        await client.aclose()
        await memory.close()
        await store.close()


async def test_memory_routes_report_501_without_a_memory_store(tmp_path: Path) -> None:
    """没装记忆库时诚实说 501，不返回一个看起来像"记忆为空"的空列表（那是两种事实）。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    surface = CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(EventServer(surface, store))), base_url="http://svc", timeout=30, trust_env=False
    )
    try:
        assert (await client.get("/memory")).status_code == 501
        assert (await client.patch("/memory", json={"entry_id": "memory/a.md:1-2", "text": "x"})).status_code == 501
    finally:
        await client.aclose()
        await store.close()
