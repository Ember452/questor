"""外部 OpenAI lane 不得裸暴露 sidecar 控制面（track4 BLK-3 / surfaces BLK-1）。

``--serve-openai`` 曾以 ``create_app(server, openai_api_keys=keys)`` 起服务但**不传会话 token**，
于是 ``/run``/``/shutdown``/``/resolve``/``/resume``/``/events`` 在 require_token=None 下对
本机/跨机任意进程开放（api_keys 只护 ``/v1``）——击穿 HITL。修法落点在 create_app：给了
openai_api_keys 却没给 token 时自动生成内部 token。这里证伪：该构造下无 token 的控制面调用必须 401。"""

from __future__ import annotations

from pathlib import Path

import httpx

from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app


async def test_openai_lane_gates_control_plane_without_token(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "db.sqlite")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=ScriptedProvider([]))
        server = EventServer(surface, store)
        # openai lane：只给 api_keys、不给会话 token（模拟 --serve-openai 的 create_app 调用）。
        app = create_app(server, openai_api_keys=["sk-test"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/run", json={"text": "hi"})).status_code == 401
            assert (await client.post("/shutdown")).status_code == 401
            # /health 就绪探针仍开放（设计如此）。
            assert (await client.get("/health")).status_code == 200
    finally:
        await store.close()
