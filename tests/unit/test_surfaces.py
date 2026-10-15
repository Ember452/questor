"""P1 T10 DoD —— CLI 装配 + SSE 帧形状 + 应用路由（离线、Echo provider）。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.events import Envelope, EventType
from questor.providers.fake import EchoProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app, envelope_to_frame


async def test_cli_run_once_streams_and_completes(tmp_path: Path) -> None:
    surface = CliSurface(workspace_root=tmp_path, provider=EchoProvider())
    received: list[str] = []
    run = await surface.run_once("hello", on_delta=received.append)
    from questor.contracts.state_schema import RunStatus

    assert run.status is RunStatus.COMPLETED
    assert "".join(received)  # some text streamed to the surface


def test_envelope_to_frame_has_resume_id() -> None:
    env = Envelope(v=1, seq=7, run_id="run_z", type=EventType.RUN_COMPLETED, data={"usage": {}})
    frame = envelope_to_frame(env)
    assert frame["id"] == "7"  # Last-Event-ID cursor
    assert frame["event"] == "run_completed"
    import json

    assert json.loads(frame["data"])["seq"] == 7


async def test_event_server_stream_replays_after_seq(tmp_path: Path) -> None:
    store = await SQLiteStore(":memory:").connect()
    server = EventServer(CliSurface(workspace_root=tmp_path, provider=EchoProvider()), store)
    run_id = await server.start_run("hi")
    # drain the live/replay stream to the terminal event
    seen = []
    async for frame in server.stream(run_id, after_seq=0):
        seen.append(frame)
    types = [f["event"] for f in seen]
    assert "run_started" in types and "run_completed" in types
    # reconnect: after the first event, we must NOT re-receive it (no dup)
    first_id = int(seen[0]["id"])
    tail = [f async for f in _drain(server, run_id, first_id)]
    assert all(int(f["id"]) > first_id for f in tail)
    await store.close()


async def _drain(server: EventServer, run_id: str, after: int):
    async for frame in server.stream(run_id, after):
        yield frame


def test_create_app_has_routes() -> None:
    import asyncio

    async def _mk():
        return EventServer(CliSurface(provider=EchoProvider()), await SQLiteStore(":memory:").connect())

    server = asyncio.run(_mk())
    app = create_app(server)
    paths = {r.path for r in app.routes}
    assert {"/run", "/cancel/{run_id}", "/events/{run_id}"} <= paths
    # 必须显式 close：store 被 server/app 的闭包循环引用，靠引用计数回收不到，
    # 其 aiosqlite 非守护工作线程会在解释器退出时把 pytest 进程卡死（CI 卡死根因）。
    asyncio.run(server.store.close())
