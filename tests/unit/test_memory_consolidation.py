"""B9/c3/c5：巩固锁、supersede 优先、有界重试与"过期不参与衰减排序"（v3 §6.5）。

判据都落在**可观察后果**上：被 supersede 的旧事实不再被召回、配额低时真的不开工、
蒸馏器抛错只试有限次且绝不冒泡打断回复。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.memory.consolidate import (
    MAX_DISTILL_ATTEMPTS,
    consolidate,
    lock_for,
    reset_consolidation_locks,
    supersede,
)
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


class _Outcome:
    def __init__(self, new_core: str | None, dream: str = "consolidated") -> None:
        self.new_core = new_core
        self.dream = dream


class _Flaky:
    """前 ``fail_times`` 次抛错，之后成功（验证有界重试）。"""

    def __init__(self, fail_times: int, *, none_result: bool = False) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.none_result = none_result

    async def distill(self, core, dailies):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("distiller exploded")
        if self.none_result:
            return None
        return _Outcome("# MEMORY\n- consolidated fact\n")


@pytest.fixture(autouse=True)
def _clean_locks() -> object:
    reset_consolidation_locks()
    yield
    reset_consolidation_locks()


async def test_superseded_fact_is_never_recalled_again(tmp_path: Path) -> None:
    """§13 B9 验收：supersede 后旧事实不再召回（先退役、再写替代）。"""
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="the vendor is ACME-CORP-77", attributed_to="user"),
            idempotency_key="old",
        )
        hits = await store.search("ACME-CORP-77", k=3)
        assert hits and "ACME-CORP-77" in hits[0].snippet
        entry_id = f"{hits[0].path}:{hits[0].start_line}-{hits[0].end_line}"
        outcome = await supersede(
            store,
            entry_id=entry_id,
            replacement=MemoryWrite(
                kind=MemoryWriteKind.DAILY,
                scope=MemoryScope.USER,
                text="the vendor is GLOBEX now",
                attributed_to="user",
            ),
            idempotency_key="sup-1",
        )
        assert outcome.superseded == 1 and outcome.wrote is True
        assert await store.search("ACME-CORP-77", k=3) == ()  # 旧事实退役，不再被召回
        fresh = await store.search("GLOBEX", k=3)
        assert fresh and "GLOBEX" in fresh[0].snippet
    finally:
        await store.close()


async def test_consolidation_locks_per_session_and_is_non_destructive(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="fact one about budgets"),
            idempotency_key="c1",
        )
        concurrent: list = []

        async def _run(tag: str) -> None:
            outcome = await consolidate(store, _Flaky(0), session_id="s-a", lookback_days=3)
            concurrent.append((tag, outcome.wrote, outcome.attempts))

        await asyncio.gather(_run("a"), _run("b"))
        assert lock_for("s-a") is lock_for("s-a")
        assert lock_for("s-a") is not lock_for("s-b")  # 锁按会话分，不全局串行
        core = await store.read_memory_text("MEMORY.md")
        assert "consolidated fact" in core  # 巩固确实写回
        daily = await store.list_memory_paths()
        assert any(path.startswith("memory/") for path in daily)  # 非破坏式：daily 真源仍在
        assert all(wrote for _tag, wrote, _attempts in concurrent)
    finally:
        await store.close()


async def test_consolidation_retries_bounded_and_never_raises(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        always_fail = _Flaky(99)
        outcome = await consolidate(store, always_fail, session_id="s-fail")
        assert outcome.wrote is False
        assert outcome.attempts == MAX_DISTILL_ATTEMPTS  # 有界：绝不无限重试
        assert always_fail.calls == MAX_DISTILL_ATTEMPTS
        assert outcome.reason.startswith("distill_error")
        empty = await consolidate(store, _Flaky(0, none_result=True), session_id="s-empty")
        assert empty.wrote is False and empty.reason == "nothing_to_consolidate"
    finally:
        await store.close()


async def test_expired_memory_stays_out_of_ranking_even_after_decay(tmp_path: Path) -> None:
    """纪律⑦：过期条目直接退出检索，而不是"靠衰减排到后面"。"""
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        await store.write(
            MemoryWrite(
                kind=MemoryWriteKind.DAILY,
                scope=MemoryScope.USER,
                text="expired fact about the launch window",
                expires_at=datetime.now(UTC) - timedelta(seconds=5),
            ),
            idempotency_key="e1",
        )
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="live fact about the launch window"),
            idempotency_key="e2",
        )
        hits = await store.search("launch window", k=10)
        assert hits and all("expired fact" not in hit.snippet for hit in hits)
        assert any("live fact" in hit.snippet for hit in hits)
        # 过期行仍在索引里（软删/过期是行内事实，不做物理删除；真源也仍是文件）。
        row = await store._db.execute("SELECT COUNT(*) FROM memory_chunks WHERE expires_at IS NOT NULL")  # type: ignore[union-attr]
        assert (await row.fetchone())[0] == 1
    finally:
        await store.close()
