"""P7 §6-8：`resync_required` 分因——after_seq 超过 durable 头（ahead）时出声而非静默空重放。"""

from __future__ import annotations

from questor.contracts.events import EventType
from questor.kernel.events import InProcessEventBus


class _HeadStore:
    """够 subscribe 用的最小 store 替身：只暴露 sequence_head/replay（durable 头可控）。"""

    def __init__(self, head: int) -> None:
        self._head = head

    async def sequence_head(self, run_id: str) -> int:
        return self._head

    async def replay(self, run_id: str, after_seq: int, limit=None):  # noqa: ANN001
        return []


async def test_after_seq_beyond_head_emits_resync_ahead() -> None:
    bus = InProcessEventBus(_HeadStore(head=3))
    frames = [env async for env in bus.subscribe("run_x", after_seq=10)]
    assert [f.type for f in frames] == [EventType.RESYNC_REQUIRED], frames
    data = frames[0].data
    assert data["reason"] == "after_ahead", data
    assert data["current"] == 3 and data["expected"] == 10, data


async def test_after_seq_at_head_does_not_resync() -> None:
    # after_seq <= head：不触发 ahead 闸门（走正常订阅路径，不立即产 resync）。
    bus = InProcessEventBus(_HeadStore(head=10))
    gen = bus.subscribe("run_x", after_seq=5)
    first = await _first_or_none(gen)
    assert first is None or first.type != EventType.RESYNC_REQUIRED


async def _first_or_none(agen):  # noqa: ANN001, ANN202
    import asyncio

    task = asyncio.ensure_future(agen.__anext__())
    try:
        await asyncio.wait_for(task, timeout=0.2)
        return task.result()
    except (TimeoutError, asyncio.CancelledError, StopAsyncIteration):
        task.cancel()
        return None
