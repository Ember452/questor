"""T18：HTTP/SSE 端审批全生命周期（request → resolve → resolved → started → completed）。

危险写（无沙箱围栏下的 write）触发 ask；HTTP 侧 resolve_approval 只经 inbox 提交 Command，
SSE 客户端在同一条流上看到审批请求、审批解决、工具开/闭、run 终态。
"""

from __future__ import annotations

import asyncio

from questor.contracts.events import EventType
from questor.contracts.ports import StreamChunk
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer


def _write_turn() -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc1", "name": "write", "args_delta": '{"file_path": "out.txt", "content": "hi"}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


def _finish_turn() -> list[StreamChunk]:
    return [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]


async def test_sse_approval_lifecycle(tmp_path) -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, provider=ScriptedProvider([_write_turn(), _finish_turn()]))
        server = EventServer(surface, store)
        run_id = await server.start_run("write out.txt", run_id="run-sse")

        seen: list[str] = []
        resolved = False
        async for env in server.bus.subscribe(run_id, 0):
            seen.append(env.type)
            if env.type == EventType.APPROVAL_REQUEST and not resolved:
                receipt = await server.resolve_approval(run_id, env.data["request_id"], "allow")
                assert receipt.status.value == "accepted"
                resolved = True
                # 重复提交同一 request 应幂等（duplicate，映射 200）。
                dup = await server.resolve_approval(run_id, env.data["request_id"], "allow")
                assert dup.status.value == "duplicate"
            if env.type in {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}:
                break

        assert EventType.APPROVAL_REQUEST in seen
        assert EventType.APPROVAL_RESOLVED in seen
        assert EventType.TOOL_STARTED in seen
        assert EventType.TOOL_COMPLETED in seen
        assert EventType.RUN_COMPLETED in seen
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi"
    finally:
        await asyncio.sleep(0)
        await store.close()


async def test_resolve_unknown_run_maps_404(tmp_path) -> None:
    from fastapi import HTTPException

    store = await SQLiteStore(":memory:").connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path), store)
        try:
            await server.resolve_approval("nope", "apr", "allow")
        except HTTPException as exc:
            assert exc.status_code == 404
        else:  # pragma: no cover
            raise AssertionError("expected HTTPException 404")
    finally:
        await store.close()
