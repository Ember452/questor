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


# ---- P3 T4/T5: dual cursor watermark + cross-run catch-up + resume discovery (ADR-0011/0022) ----


async def test_watermark_is_global_monotonic_across_runs(store) -> None:
    # per-run logical seq restarts at 1; the global physical watermark grows monotonically across runs.
    assert await store.watermark() == 0
    await store.append("run_a", ({"type": "run_started", "data": {}}, {"type": "message_completed", "data": {}}))
    await store.append("run_b", ({"type": "run_started", "data": {}},))
    assert await store.sequence_head("run_a") == 2 and await store.sequence_head("run_b") == 1  # per-run isolated
    assert await store.watermark() == 3  # 3 durable events total, global order


async def test_replay_global_catchup_across_runs(store) -> None:
    await store.append("run_a", ({"type": "run_started", "data": {}},))
    mark = await store.watermark()  # 1
    await store.append("run_b", ({"type": "run_started", "data": {}}, {"type": "turn_started", "data": {}}))
    rows = await store.replay_global(after_watermark=mark)
    # catch-up returns exactly the events written after the watermark, across both runs, in gseq order
    assert [r["run_id"] for r in rows] == ["run_b", "run_b"]
    assert [r["gseq"] for r in rows] == [2, 3]
    assert all(r["gseq"] > mark for r in rows)


async def test_replay_exposes_gseq(store) -> None:
    await store.append("run_a", ({"type": "run_started", "data": {}},))
    row = (await store.replay("run_a", after_seq=0))[0]
    assert "gseq" in row and row["gseq"] >= 1


async def test_list_unfinished_runs_derives_from_log(store) -> None:
    await store.append("run_open", ({"type": "run_started", "data": {}}, {"type": "tool_completed", "data": {}}))
    await store.append("run_done", ({"type": "run_started", "data": {}}, {"type": "run_completed", "data": {}}))
    unfinished = await store.list_unfinished_runs()
    assert "run_open" in unfinished
    assert "run_done" not in unfinished  # log has a terminal event -> not resumable


async def test_checkpoint_seq(store) -> None:
    assert await store.checkpoint_seq("run_e") is None
    await store.save_checkpoint(
        {"cp_id": "cp_1", "run_id": "run_e", "seq": 7, "turn": 3, "kind": "auto", "state_digest": "{}", "pending": []}
    )
    assert await store.checkpoint_seq("run_e") == 7


async def test_schema_version_fail_closed(tmp_path) -> None:
    from questor.providers.store_sqlite import SQLiteStore, StoreSchemaVersionError

    path = str(tmp_path / "db.sqlite")
    s = await SQLiteStore(path).connect()
    await s.append("run_a", ({"type": "run_started", "data": {}},))
    await s.close()

    reopened = await SQLiteStore(path).connect()  # same version -> opens fine
    assert await reopened.watermark() == 1
    await reopened.close()

    # simulate a DB written by a newer, unknown schema version -> must refuse to half-read
    import aiosqlite

    async with aiosqlite.connect(path) as con:
        await con.execute("UPDATE meta SET value = '99999' WHERE key = 'store_schema_version'")
        await con.commit()
    with pytest.raises(StoreSchemaVersionError):
        await SQLiteStore(path).connect()
