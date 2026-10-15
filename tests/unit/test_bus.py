"""P1 T8 DoD — bus: persist durable, forward live-only, terminal uniqueness, version gate."""

from __future__ import annotations

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
    bus = InProcessEventBus(await SQLiteStore(":memory:").connect())
    got = [e async for e in bus.subscribe("run_d", 0, expected_version=999)]
    assert [e.type for e in got] == ["resync_required"]


async def test_internal_only_event_not_forwarded_but_persisted() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_e", "checkpoint_recorded"))  # internal-only
    await bus.emit(_env(2, "run_e", EventType.RUN_COMPLETED))  # terminal -> ends the stream
    assert await store.sequence_head("run_e") == 2  # both persisted internally
    got = [e async for e in bus.subscribe("run_e", 0)]
    assert [e.type for e in got] == ["run_completed"]  # projection drops the internal event
    await store.close()
