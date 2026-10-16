"""P3 E2：SSE 版本闸门的**消费者**接线 —— EventServer/`/events` 把客户端契约版本透传给总线。

design/02 §10 要求"续传前版本闸门、禁新版本解旧事件"。P3 之前机制在
``InProcessEventBus.subscribe`` 已具备，但 surfaces 从不传 ``expected_version`` → 实时重连路径闸门是死的。
本测试证明消费者已接上：不匹配 → 只发一条 ``resync_required`` 后停，绝不后续解码。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.events import EVENT_SCHEMA_VERSION
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer


async def test_http_stream_version_gate_emits_resync_then_stops(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "gate.db")).connect()
    server = EventServer(CliSurface(workspace_root=tmp_path, store=store), store)

    frames = [f async for f in server.stream("run_any", 0, expected_version=EVENT_SCHEMA_VERSION + 1)]
    assert [f["event"] for f in frames] == ["resync_required"]  # 一条即停，无后续跨版本事件

    await store.close()
