"""B13 体验面（可退）HTTP：`POST /runs/{id}/rewind` 与 `POST /sessions/{id}/fork`。

判据只有两件事：**新流有事实**（回退/分叉本身可回放），**旧流一字不动**。
回退必须在创建点就落 prelude——先 start 再投 inbox 会跟驱动赛跑，Echo provider 一轮就终态，
那时 RewindRun 只会被 reduce 拒成一条 warning（这里专门把它钉住）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from questor.contracts.events import ForkSession, RewindRun
from questor.kernel.session_ops import session_stream_id
from questor.providers.fake import EchoProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app


async def _wait_types(store: SQLiteStore, run_id: str, wanted: set[str], *, timeout: float = 10.0) -> list[dict]:
    """轮询到指定事件类型出现为止（后台驱动 task 不是同步完成的）。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        rows = await store.replay(run_id, 0)
        if wanted <= {row["type"] for row in rows}:
            return rows
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timeout waiting for {wanted} on {run_id}; got {[r['type'] for r in rows]}")
        await asyncio.sleep(0.02)


async def _client(store: SQLiteStore, tmp_path: Path) -> httpx.AsyncClient:
    server = EventServer(CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider()), store)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(server)), base_url="http://svc", timeout=30, trust_env=False)


async def test_rewind_starts_a_new_run_and_leaves_the_base_stream(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    client = await _client(store, tmp_path)
    try:
        base_run = await client.post("/run", json={"text": "first take", "session_id": "sess-a"})
        assert base_run.status_code == 200
        base_id = base_run.json()["run_id"]
        base_rows = await _wait_types(store, base_id, {"run_completed"})
        before = [(row["seq"], row["type"]) for row in base_rows]

        res = await client.post(f"/runs/{base_id}/rewind", json={"to_seq": 1, "text": "second take", "reason": "try differently"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["base_run_id"] == base_id and body["base_to_seq"] == 1
        new_id = body["run_id"]
        assert new_id != base_id

        new_rows = await _wait_types(store, new_id, {"run_rewounded", "run_completed"})
        rewinds = [row for row in new_rows if row["type"] == "run_rewounded"]
        assert len(rewinds) == 1  # 回退事实恰一条，且落在**新**流上
        assert rewinds[0]["data"]["base_run_id"] == base_id
        # 旧流逐行不变：回退不是"删掉后半段"，只是新开一条线
        after = [(row["seq"], row["type"]) for row in await store.replay(base_id, 0)]
        assert after == before
    finally:
        await client.aclose()
        await store.close()


async def test_rewind_rejects_a_negative_anchor(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    client = await _client(store, tmp_path)
    try:
        res = await client.post("/runs/run-anything/rewind", json={"to_seq": -3})
        assert res.status_code == 400
        assert (await client.post("/runs/run-anything/rewind", json={"to_seq": "abc"})).status_code == 400
    finally:
        await client.aclose()
        await store.close()


async def test_fork_writes_the_new_session_stream_only(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    client = await _client(store, tmp_path)
    try:
        run = await client.post("/run", json={"text": "hello", "session_id": "sess-src"})
        assert run.status_code == 200
        await _wait_types(store, run.json()["run_id"], {"run_completed"})

        res = await client.post("/sessions/sess-src/fork", json={"from_seq": 2, "reason": "branch off"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source_session_id"] == "sess-src" and body["from_seq"] == 2
        new_sid = body["session_id"]
        assert new_sid and new_sid != "sess-src"

        rows = await store.replay(session_stream_id(new_sid), 0)
        assert [row["type"] for row in rows] == ["session_forked"]
        assert rows[0]["data"]["source_session_id"] == "sess-src"
        # 源会话流上只有它自己的 B9 记忆/结算事实，绝不会冒出 session_forked
        src_rows = await store.replay(session_stream_id("sess-src"), 0)
        assert "session_forked" not in {row["type"] for row in src_rows}
        # 会话表仍是唯一的一张：新会话就是一行 sessions，没有第二张结构
        assert (await store.session_row(new_sid))["session_id"] == new_sid
    finally:
        await client.aclose()
        await store.close()


def test_session_commands_stay_pure_data() -> None:
    """命令是纯数据：不带 store 句柄、不带正文之外的可执行物（C4：策略/surface 无裸写句柄）。"""
    rewind = RewindRun(run_id="a", base_run_id="b", base_to_seq=1)
    fork = ForkSession(run_id="a", source_session_id="sess", from_seq=0)
    assert rewind.type == "rewind_run" and fork.type == "fork_session"
    assert set(rewind.__dataclass_fields__) == {"run_id", "base_run_id", "base_to_seq", "reason", "type"}
