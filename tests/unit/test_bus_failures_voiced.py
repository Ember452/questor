"""刀1 缺陷 A②：总线故障必须出声（questor.bus 现为定义于 events.py:28 的死 logger）。

注入两条故障路径，断言 ``questor.bus`` 出现 WARNING：
- 持久化失败（store.append 抛错）：记录后**仍上冒**（数据丢失不可静默吞，保持既有致命语义）。
- 订阅者队列溢出（有界队列满）：记录后**吞掉**该帧（背压丢帧，消费者可 resync，不拖垮 loop）。

判红前置：T1.2 实现之前，persist 失败直接上冒且无 WARNING、溢出路径不存在 → 两条必红。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest

from questor.contracts.events import EVENT_SCHEMA_VERSION, Envelope, EventType
from questor.kernel.events import InProcessEventBus


def _env(run_id: str, seq: int) -> Envelope:
    return Envelope(
        v=EVENT_SCHEMA_VERSION,
        seq=seq,
        run_id=run_id,
        type=EventType.RUN_COMPLETED,
        turn=1,
        data={"usage": {"input": 1, "output": 1}, "exit_reason": "completed"},
        ts=datetime.now(UTC),
    )


class _BoomStore:
    """最小 StorePort 替身：append 必抛（模拟磁盘满/持久化失败）。"""

    async def append(self, run_id: str, rows) -> None:  # noqa: ANN001
        raise OSError("disk full")


class _CountingBoomStore:
    """append 必抛且计数调用次数（W5-012）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def append(self, run_id: str, rows) -> None:  # noqa: ANN001
        self.calls += 1
        raise OSError("disk full")


async def test_terminal_persist_failure_not_swallowed_on_retry() -> None:
    """W5-012：append 失败不得把 run 记进 _closed，否则重投的终态在入口被静默吞。"""
    store = _CountingBoomStore()
    bus = InProcessEventBus(store=store)  # type: ignore[arg-type]
    for _ in range(2):
        with pytest.raises(OSError):
            await bus.emit(_env("run-poison", 1))
    assert store.calls == 2, f"后续终态被静默吞（append 只调用 {store.calls} 次）"
    assert "run-poison" not in bus._closed


async def test_closed_set_is_bounded() -> None:
    """W5-012：_closed 有界 FIFO，不随 run 数无界增长。"""

    class _OkStore:
        async def append(self, run_id: str, rows) -> None:  # noqa: ANN001
            return None

    bus = InProcessEventBus(store=_OkStore())  # type: ignore[arg-type]
    for i in range(bus._CLOSED_MAX + 500):
        await bus.emit(_env(f"run-{i}", 1))
    assert len(bus._closed) <= bus._CLOSED_MAX


async def test_persist_failure_is_voiced_then_reraised(caplog: pytest.LogCaptureFixture) -> None:
    bus = InProcessEventBus(store=_BoomStore())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="questor.bus"):
        with pytest.raises(OSError):
            await bus.emit(_env("run-persist-fail", 1))
    assert any(r.name == "questor.bus" and r.levelno >= logging.WARNING for r in caplog.records), (
        "persist failure must be logged on questor.bus"
    )


async def test_subscriber_queue_overflow_is_voiced(caplog: pytest.LogCaptureFixture) -> None:
    bus = InProcessEventBus()
    run_id = "run-queue-full"
    bus.add_subscriber(run_id)
    full: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=1)
    full.put_nowait(_env(run_id, 0))  # 先占满，使后续 put_nowait 触发 QueueFull
    bus._subs[run_id] = [full]  # 用有界满队列替换默认无界队列以注入溢出

    with caplog.at_level(logging.WARNING, logger="questor.bus"):
        await bus.emit(_env(run_id, 2))  # 不得抛出：溢出丢帧 + 出声告警

    assert any(r.name == "questor.bus" and r.levelno >= logging.WARNING for r in caplog.records), (
        "subscriber overflow must be logged on questor.bus"
    )
