"""地基不变式：任何驱动一个 run 的路径都必须在单写者租约栅栏下（C2/ADR-0047）。

真问题（审计 track4 BLK-2b）：``EventServer.start_run`` 从不取租约（只有 ``resume`` 取）。于是
进程 A ``start_run`` 正在驱的 run，进程 B（或同进程另一路）``--resume`` 合法取到租约 → 双驱同一
run_id → 两条逻辑事件流交错 append（SQLite BEGIN IMMEDIATE 只保证单事务不撕裂，不阻止两 driver）。
这里用阻塞 provider 让 run 保持"驱动中"，证伪：start_run 期间异 holder 取同一 run 租约必须被拒。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.ports import StreamChunk
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer


class _BlockingProvider:
    """stream 阻塞在 release 之前不产出 → run 停在驱动中，租约必须一直被持有。"""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream(self, request):  # -> AsyncIterator[StreamChunk]
        await self.release.wait()
        yield StreamChunk(kind="text", text="done")
        yield StreamChunk(kind="finish", finish_reason="stop")


async def test_start_run_holds_single_writer_lease(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "db.sqlite")).connect()
    try:
        provider = _BlockingProvider()
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=provider)  # type: ignore[arg-type]
        server = EventServer(surface, store)

        run_id = await server.start_run("hi")
        # 先拿住驱动任务引用（完成后 registry 会回收，_runs 会变空）。
        active = server.registry._runs.get(run_id)
        assert active is not None and active.task is not None
        task = active.task
        # run 正在驱动（provider 阻塞中）：异 holder 取同一 run 租约必须被栅栏拒（单写者）。
        foreign = await store.acquire_lease(run_id, "foreign-driver", 1, ttl_seconds=300.0)
        assert foreign is False, "start_run 未持有租约 → 另一 driver 可抢驱同 run（BLK-2b）"

        # 收尾：放行 provider，run 落终态并释放租约 → 此后异 holder 可取。
        provider.release.set()
        await task
        after = await store.acquire_lease(run_id, "foreign-driver", 1, ttl_seconds=300.0)
        assert after is True, "run 完成后租约应已释放"
        await store.release_lease(run_id, "foreign-driver", 1)
    finally:
        await store.close()
