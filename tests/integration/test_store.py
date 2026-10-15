"""P1 T9 DoD —— 事件溯源：after_seq 重放（不丢不重）+ head + checkpoint。"""

from __future__ import annotations

import pytest

from questor.providers.store_sqlite import SQLiteStore


@pytest.fixture
async def store():
    s = await SQLiteStore(":memory:").connect()
    yield s
    await s.close()


async def test_append_assigns_per_run_logical_seq(store) -> None:
    last = await store.append(
        "run_a",
        ({"type": "run_started", "data": {"run_id": "run_a"}}, {"type": "message_completed", "turn": 1, "data": {}}),
    )
    assert last == 2
    assert await store.sequence_head("run_a") == 2


async def test_replay_after_seq_no_loss_no_dup(store) -> None:
    await store.append("run_b", tuple({"type": f"t{i}", "data": {"i": i}} for i in range(5)))
    all_events = await store.replay("run_b", after_seq=0)
    assert [e["seq"] for e in all_events] == [1, 2, 3, 4, 5]
    resumed = await store.replay("run_b", after_seq=3)
    assert [e["seq"] for e in resumed] == [4, 5]  # exactly the missed tail


async def test_sequences_isolated_per_run(store) -> None:
    await store.append("run_c", ({"type": "x", "data": {}},))
    await store.append("run_d", ({"type": "y", "data": {}},))
    assert await store.sequence_head("run_c") == 1
    assert await store.sequence_head("run_d") == 1


async def test_checkpoint_roundtrip(store) -> None:
    cp = {"cp_id": "cp_1", "run_id": "run_e", "seq": 4, "turn": 2, "kind": "auto", "state_digest": "sha:abc", "pending": ["tc_9"]}
    await store.save_checkpoint(cp)
    loaded = await store.latest_checkpoint("run_e")
    assert loaded is not None
    assert loaded["seq"] == 4
    assert loaded["pending"] == ["tc_9"]
    assert await store.latest_checkpoint("missing") is None


async def test_store_requires_connect() -> None:
    from questor.providers.store_sqlite import SQLiteStore as S

    with pytest.raises(RuntimeError):
        await S(":memory:").append("run_x", ({"type": "t", "data": {}},))
