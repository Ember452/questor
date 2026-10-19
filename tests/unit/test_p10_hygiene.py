"""P10 TD1/TD2（TDD）—— 卫生回收：lease/TTL 账本回收 + artifact 可达性孤儿 GC。

承 ADR-0050 边界：**只回收瞬态派生视图**（过期/已释放 lease、超 TTL 未 ack claim），
**绝不删已 acked 的投递行**（BLK-2：删了 rebuild 重 claim→双投破 exactly-once）；
artifact GC **只删孤儿**（不被任何引用命中），活跃引用恒保留（去重安全）。
"""

from __future__ import annotations

import time
from pathlib import Path

from questor.providers.artifact_store import FileSystemArtifactStore, referenced_artifact_ids
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.maintenance import run_maintenance_command


async def test_reclaim_expired_leases_only_expired(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        # 过期租约：ttl 负 → 立即过期；未过期：长 ttl
        await store.acquire_lease("run_expired", "h1", 1, ttl_seconds=-1.0)
        await store.acquire_lease("run_live", "h2", 1, ttl_seconds=3600.0)
        removed = await store.reclaim_expired_leases(time.time())
        assert removed == 1  # 只删过期的
        # 未过期租约仍在：同 holder/epoch renew 成功证明行未被删
        assert await store.renew_lease("run_live", "h2", 1) is True
    finally:
        await store.close()


async def test_reclaim_stale_claims_never_touches_acked(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        # 超时未 ack 的 in-flight claim
        await store.claim_delivery("d_stale", ttl_seconds=-1.0)
        # 已 acked 的投递（幂等键，必须保留）
        await store.claim_delivery("d_acked", ttl_seconds=3600.0)
        assert await store.ack_delivery("d_acked") is True

        removed = await store.reclaim_stale_claims(time.time())
        assert removed == 1  # 只删超时未 ack 的
        assert await store.delivery_state("d_stale") is None  # 已回收
        assert await store.delivery_state("d_acked") == "acked"  # BLK-2：acked 绝不被删

        # 再跑一次：acked 仍安全（幂等、无谓删）
        assert await store.reclaim_stale_claims(time.time()) == 0
        assert await store.delivery_state("d_acked") == "acked"
    finally:
        await store.close()


async def test_artifact_gc_removes_only_orphans(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path)
    await store.connect()
    kept = await store.put_text("referenced body", run_id="r1", kind="tool_output")
    orphan = await store.put_text("orphan body", run_id="r1", kind="tool_output")
    assert kept.artifact_id != orphan.artifact_id

    referenced = {kept.artifact_id}  # 只有 kept 被事件引用；orphan 是写成功但崩于发事件前
    removed = await store.gc_orphans(referenced)
    assert removed == [orphan.artifact_id]

    # 被引用的仍在（dry_run 再删一次应为空）
    again = await store.gc_orphans(referenced, dry_run=True)
    assert orphan.artifact_id not in again  # 已被真删
    assert kept.artifact_id not in again  # 活跃引用永不删


def test_referenced_artifact_ids_scans_nested_events() -> None:
    events = [
        {"type": "tool_completed", "data": {"artifact_ref": "artifact://abc123", "status": "success"}},
        {"type": "peer_ended", "data": {"result_ref": "artifact://def456"}},
        {"type": "run_completed", "data": {"usage": {}}},  # 无引用
    ]
    ids = referenced_artifact_ids(events)
    assert ids == {"artifact://abc123", "artifact://def456"}


async def test_maintenance_command_reclaims_via_production_caller(tmp_path: Path) -> None:
    """Minor-2：`questor maintenance` 给 reclaim 方法一个生产调用方（不再是零 caller）。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        await store.acquire_lease("run_exp", "h", 1, ttl_seconds=-1.0)
        await store.claim_delivery("d_stale", ttl_seconds=-1.0)
        out = await run_maintenance_command(store)
        assert "reclaimed_leases=1" in out
        assert "reclaimed_stale_claims=1" in out
    finally:
        await store.close()
