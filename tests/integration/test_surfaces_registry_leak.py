"""地基不变式：run 驱动完成必须从 ``RunRegistry`` 回收 controller（长驻 sidecar 不泄漏）。

真问题（审计 surfaces MAJ-2 / track4 MAJ-17）：``EventServer.start_run`` 注册 controller，但
``RunRegistry.unregister`` **只在 SSE ``stream()`` 见终态时**调用。于是无人订阅的 run（HTTP ``POST /run``
后不连 ``/events``、``--serve-openai`` 非流式聚合、子 agent 完成）驱动结束后永驻 ``registry._runs``
→ 常驻 sidecar 内存单调递增。这里证伪：run 后台驱动到终态后，注册表必须清空该 run。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.ports import StreamChunk
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer

_ANSWER = [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]


async def test_start_run_without_subscriber_unregisters_after_completion(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "db.sqlite")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=ScriptedProvider([_ANSWER]))
        server = EventServer(surface, store)
        run_id = await server.start_run("hi")
        assert server.registry.get(run_id) is not None  # 运行中已注册

        active = server.registry._runs.get(run_id)
        task = active.task if active else None
        assert task is not None
        await task  # 驱动到终态；全程无人订阅 SSE stream

        assert server.registry.get(run_id) is None, "run 完成后 controller 未从注册表回收（泄漏）"
    finally:
        await store.close()
