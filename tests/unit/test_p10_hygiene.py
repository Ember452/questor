"""P10 TD1/TD2（TDD）—— 卫生回收：lease/TTL 账本回收 + artifact 可达性孤儿 GC。

承 ADR-0050 边界：**只回收瞬态派生视图**（过期/已释放 lease、超 TTL 未 ack claim），
**绝不删已 acked 的投递行**（BLK-2：删了 rebuild 重 claim→双投破 exactly-once）；
artifact GC **只删孤儿**（不被任何引用命中），活跃引用恒保留（去重安全）。
"""

from __future__ import annotations

import time
from dataclasses import fields
from pathlib import Path

from questor.contracts.memory import MemorySearchResult, MemorySource
from questor.contracts.state_schema import ToolCall
from questor.providers.artifact_store import FileSystemArtifactStore, referenced_artifact_ids
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run, ToolLedger
from questor.state.reduce import _tool_completed_data
from questor.state.snapshot import from_snapshot, to_snapshot
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


# ---- G7 僵尸位：artifact_ref 家族先拆同名、再判死活（不得直删）--------------- #
def test_artifact_ref_family_is_three_distinct_symbols_not_one() -> None:
    """§21 G7：“同名不同物”必须先拆开，否则“删死字段”会删掉活代码。"""
    tool_call_fields = {field.name for field in fields(ToolCall)}
    memory_hit_fields = {field.name for field in fields(MemorySearchResult)}
    assert "artifact_refs" in tool_call_fields  # 复数：账本上的引用列表
    assert "artifact_ref" in memory_hit_fields  # 单数：记忆命中的外置指针
    assert "artifact_refs" not in memory_hit_fields and "artifact_ref" not in tool_call_fields
    # 第三个同名物是 dict 键（envelope_for_text 的产物），不是 dataclass 字段。
    assert "artifact_ref" in _archived_envelope()["result"]


def test_toolcall_artifact_refs_round_trips_through_snapshot() -> None:
    """判决：**活字段**（快照往返不丢），不能删。"""
    call = ToolCall(tool_call_id="tc1", turn=1, name="read", args={}, artifact_refs=("artifact://a",))
    run = Run(run_id="run_g7", tool_ledger=ToolLedger(calls=(call,)))
    restored = from_snapshot(to_snapshot(run))
    assert restored.tool_ledger.calls[0].artifact_refs == ("artifact://a",)


def test_archived_envelope_is_the_live_producer_of_the_event_artifact_ref() -> None:
    """判决：**活链路**——`reduce` 只认归档信封里的 `artifact_ref.artifact_id`，短输出不带。"""
    envelope = _archived_envelope()["result"]
    data = _tool_completed_data("tc1", "success", result=envelope, display=None)
    assert data["artifact_ref"] == "artifact://a"
    assert data["truncated"] is True and data["preview"] == "head"
    short = _tool_completed_data("tc2", "success", result="tiny output", display=None)
    assert "artifact_ref" not in short and short["truncated"] is False


def test_memory_search_result_artifact_ref_is_a_reserved_slot_not_dead_code() -> None:
    """判决：**预留位**（当前无生产者，但属 L0 契约词汇）——保留，不删（删 = 破坏性契约变更）。"""
    hit = MemorySearchResult(
        path="MEMORY.md", start_line=1, end_line=2, score=0.5, snippet="s", source=MemorySource.CORE
    )
    assert hit.artifact_ref is None  # 超阈全文外置时才非 None（design/06 §0；ADR-0019）


def _archived_envelope() -> dict:
    """`envelope_for_text` 的产物形状（_output.py:41）；写失败不得回退原文。"""
    return {
        "result": {
            "kind": "archived_tool_result",
            "artifact_ref": {"artifact_id": "artifact://a", "sha256": "x"},
            "content_sha256": "x",
            "total_bytes": 999999,
            "preview": "head",
            "continuation": {"has_more": True, "next": {"tool_call_id": "tc1", "artifact_id": "artifact://a"}},
        }
    }
