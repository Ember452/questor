"""P1 T8 DoD —— 总线：durable 落库、live-only 转发、终态唯一、版本闸门。"""

from __future__ import annotations

import asyncio

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import InProcessEventBus
from questor.providers.store_sqlite import SQLiteStore


def _env(seq: int, run_id: str, etype: str, **data: object) -> Envelope:
    return Envelope(v=1, seq=seq, run_id=run_id, type=etype, data=dict(data))


async def test_durable_events_persist_and_replay() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_a", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_a", EventType.RUN_COMPLETED))
    got = [e async for e in bus.subscribe("run_a", 0)]
    assert [e.type for e in got] == ["run_started", "run_completed"]
    assert got[-1].type in {"run_completed"}  # replay stopped at terminal
    await store.close()


async def test_live_only_delta_is_not_persisted() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_b", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_b", EventType.TEXT_DELTA, delta="hi"))  # live-only
    assert await store.sequence_head("run_b") == 1  # delta did not consume durable seq
    await store.close()


async def test_terminal_uniqueness_first_writer_wins() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_c", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_c", EventType.RUN_COMPLETED))
    await bus.emit(_env(3, "run_c", EventType.RUN_CANCELLED))  # suppressed (already terminal)
    assert await store.sequence_head("run_c") == 2
    await store.close()


async def test_version_mismatch_yields_resync() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    got = [e async for e in bus.subscribe("run_d", 0, expected_version=999)]
    assert [e.type for e in got] == ["resync_required"]
    # 必须显式 close：aiosqlite 的工作线程是非守护线程，未 close 会永远阻塞在
    # queue.get() 上，解释器退出时 threading._shutdown() join 它 → 进程永不退出（CI 卡死根因）。
    await store.close()


async def test_internal_only_event_not_forwarded_but_persisted() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_e", "checkpoint_recorded"))  # internal-only
    await bus.emit(_env(2, "run_e", EventType.RUN_COMPLETED))  # terminal -> ends the stream
    assert await store.sequence_head("run_e") == 2  # both persisted internally
    got = [e async for e in bus.subscribe("run_e", 0)]
    assert [e.type for e in got] == ["run_completed"]  # projection drops the internal event
    await store.close()


async def test_seam_replay_then_live_no_gap_no_dup() -> None:
    """P3 T15：先订阅后重放再跟实时缝合——无论事件落在重放侧还是实时侧，都按 seq 去重（不丢不重，design/02 §4）。"""
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    # 订阅者尚未挂上：先持久化 durable 1、2。
    await bus.emit(_env(1, "run_s", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_s", EventType.MESSAGE_COMPLETED))

    collected: list[int] = []

    async def consume() -> None:
        async for e in bus.subscribe("run_s", 0):
            collected.append(e.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # 让订阅者挂上并开始重放
    await bus.emit(_env(3, "run_s", EventType.MESSAGE_COMPLETED))
    await bus.emit(_env(4, "run_s", EventType.RUN_COMPLETED))  # 终态结束流
    await asyncio.wait_for(task, timeout=5)
    assert collected == [1, 2, 3, 4]  # 无缺口、无重复（即使 3/4 同时存在于 store 与队列）
    await store.close()


async def test_live_delta_interleaved_does_not_shift_durable_seam() -> None:
    """P3 T15：live-only delta 穿插不占 durable seq，不破坏重放/实时缝合去重。"""
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_f", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_f", EventType.TEXT_DELTA, delta="x"))  # live-only, not persisted
    assert await store.sequence_head("run_f") == 1  # delta 不推进 durable head
    it = bus.subscribe("run_f", 0)
    first = await it.__anext__()  # 重放只给 durable（run_started）；live delta 不在历史里
    assert first.type == "run_started"
    await it.aclose()  # 无终态事件，显式关闭生成器避免挂在 queue.get
    await store.close()
