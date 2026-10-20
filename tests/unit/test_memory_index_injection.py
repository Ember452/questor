"""B7/c2 `[behavior]`：档1 索引段进 system 的定界静态子段 + `memory_injected` 观测（生产默认开）。

钉三件事：
1. **注入真发生**：生产路径（组合根开启）下 provider 收到的 `system` 含定界前导语与 pointer 行；
2. **既有装配面零改动**：`CliSurface.system` 仍是 skills 装配结果（逐字节 golden 契约不被本刀污染）；
3. **可归因**：发出请求时落一条 live-only `memory_injected`，且**不带正文**、永不入库。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from questor.contracts.events import EventType
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.kernel.events import InProcessEventBus
from questor.memory.index import LEAD_IN
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface


class _RecordingProvider(ProviderPort):
    """记录每次请求的 system/messages，随即礼貌收尾（单轮结束，不调工具）。"""

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        yield StreamChunk(kind="text", text="ok")
        yield StreamChunk(kind="finish", finish_reason="stop")


async def _surface(tmp_path: Path, *, enabled: bool, core_text: str = "- user prefers short answers\n") -> tuple[CliSurface, _RecordingProvider]:
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mem")).connect()
    if core_text:
        await memory.write_memory_text("MEMORY.md", f"# MEMORY\n{core_text}", idempotency_key="seed-core")
    provider = _RecordingProvider()
    surface = CliSurface(
        workspace_root=tmp_path,
        provider=provider,
        store=store,
        memory_store=memory,
        memory_index_enabled=enabled,
    )
    surface._owned = (store, memory)  # type: ignore[attr-defined]
    return surface, provider


async def _close(surface: CliSurface) -> None:
    store, memory = surface._owned  # type: ignore[attr-defined]
    await memory.close()
    await store.close()


async def test_production_surface_injects_delimited_index_into_the_request(tmp_path: Path) -> None:
    surface, provider = await _surface(tmp_path, enabled=True)
    try:
        await surface.run_once("hello")
    finally:
        await _close(surface)
    assert len(provider.requests) == 1
    system = provider.requests[0].system or ""
    assert LEAD_IN in system
    assert "user prefers short answers" in system
    # ② self.system 本身不变：注入只发生在装配出的**本轮 system**，skills/基座字节不动。
    assert LEAD_IN not in (surface.system or "")


async def test_default_off_keeps_request_byte_identical(tmp_path: Path) -> None:
    surface, provider = await _surface(tmp_path, enabled=False)
    try:
        await surface.run_once("hello")
    finally:
        await _close(surface)
    assert provider.requests[0].system == surface.system
    assert surface.memory_index is None


async def test_empty_memory_produces_no_section(tmp_path: Path) -> None:
    surface, provider = await _surface(tmp_path, enabled=True, core_text="")
    try:
        await surface.refresh_memory_index()
        assert surface.memory_index is None
        await surface.run_once("hello")
    finally:
        await _close(surface)
    assert LEAD_IN not in (provider.requests[0].system or "")


async def test_memory_injected_is_live_only_and_carries_no_body(tmp_path: Path) -> None:
    surface, _provider = await _surface(tmp_path, enabled=True)
    events: list = []
    try:
        bus = InProcessEventBus(surface.store)
        bus.add_observer(events.append)
        tool_surface = surface.registry.freeze_for_run("run_b7")
        await surface.refresh_memory_index()
        loop = surface._loop(bus, asyncio.Event(), tool_surface, run_id="run_b7")
        run = await loop.drive(Run(run_id="run_b7"), "hello")
        injected = [env for env in events if env.type == EventType.MEMORY_INJECTED]
        assert len(injected) == 1, [env.type for env in events]
        assert injected[0].data["kind"] == "index"
        assert "user prefers short answers" not in repr(dict(injected[0].data))
        # live-only：绝不占 durable seq（重放里查不到它）。
        persisted = await surface.store.replay("run_b7", 0)
        assert EventType.MEMORY_INJECTED not in {row["type"] for row in persisted}
        assert run.run_id == "run_b7"
    finally:
        await _close(surface)
