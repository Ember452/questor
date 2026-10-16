"""P3 T17：耐久守卫 —— durable 事件必经 store.append（无旁路），live-only 永不入库。

守住 ADR-0020/0005/C5/C13 的落库边界：带 store 时，凡非 ``LIVE_ONLY`` 的事件都必须落 ``event_log``
（否则 resume/审计缺账），而 ``LIVE_ONLY``（delta/progress/heartbeat/usage）绝不占 durable seq。
另验 ``rebuild_run`` 幂等（重复恢复不产新 durable 事件、不重跑副作用）。
"""

from __future__ import annotations

import json

from questor.contracts.events import EVENT_SCHEMA_VERSION, Envelope, EventType
from questor.contracts.state_schema import Budget
from questor.kernel.events import LIVE_ONLY, InProcessEventBus
from questor.kernel.recovery import rebuild_run
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.snapshot import to_snapshot


def _env(seq: int, run_id: str, etype: str) -> Envelope:
    return Envelope(v=EVENT_SCHEMA_VERSION, seq=seq, run_id=run_id, type=etype, data={})


async def test_every_durable_type_is_persisted_no_bypass() -> None:
    """每个非 live-only 事件类型都必须落库；live-only 一律不落（无旁路）。"""
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    checked_persisted = 0
    checked_live = 0
    all_types = sorted(v for v in vars(EventType).values() if isinstance(v, str))
    assert all_types, "EventType exposes no string constants"
    for index, etype in enumerate(all_types):
        run_id = f"run_{index}"
        await bus.emit(_env(1, run_id, etype))
        persisted = await store.replay(run_id, 0)
        if etype in LIVE_ONLY:
            assert persisted == [], f"live-only {etype} must NOT persist"
            checked_live += 1
        else:
            assert len(persisted) == 1 and persisted[0]["type"] == etype, f"durable {etype} bypassed append"
            checked_persisted += 1
    assert checked_persisted > 0 and checked_live > 0
    await store.close()


async def test_watermark_counts_only_durable_events() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    await bus.emit(_env(1, "run_w", EventType.RUN_STARTED))
    await bus.emit(_env(2, "run_w", EventType.TEXT_DELTA))  # live-only, not persisted
    await bus.emit(_env(2, "run_w", EventType.MESSAGE_COMPLETED))  # durable (its own seq)
    # watermark = 已落库的 durable 事件条数（live-only 不占全局物理序）
    assert await store.watermark() == 2
    await store.close()


async def test_rebuild_run_is_idempotent(tmp_path) -> None:
    """同一 run 反复 rebuild 不产新 durable 事件、seq 稳定、幂等（恢复不重复副作用）。"""
    db = str(tmp_path / "idem.db")
    store = await SQLiteStore(db).connect()
    run = Run(run_id="run_idem", budget=Budget())
    await store.append("run_idem", ({"type": "run_started", "data": {}},))
    await store.save_checkpoint({"cp_id": "cp1", "run_id": "run_idem", "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": []})
    head_before = await store.watermark()

    first = await rebuild_run(store, "run_idem")
    second = await rebuild_run(store, "run_idem")
    assert first is not None and second is not None
    assert first.seq == second.seq  # 稳定，不随重复恢复漂移
    assert await store.watermark() == head_before  # rebuild 只读，不追加事件
    await store.close()
