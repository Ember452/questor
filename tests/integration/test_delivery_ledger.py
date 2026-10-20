"""B11 交付账本：扩列/五态/三 sweep/裁剪 + 触发只经 submissions（v3 §8/§9）。"""

from __future__ import annotations

import aiosqlite

from questor.contracts.events import ReportChildTerminal
from questor.providers.store_sqlite import SQLiteStore
from questor.schedule import Scheduler, current_execution_identity
from questor.surfaces.logs import run_logs_command
from questor.surfaces.subagent_orchestrator import SubagentOrchestrator


async def test_old_v3_deliveries_migrate_and_obligation_is_idempotent(tmp_path) -> None:
    path = str(tmp_path / "old.db")
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, state TEXT NOT NULL, claimed_at REAL NOT NULL, ttl_seconds REAL NOT NULL);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta (key, value) VALUES ('store_schema_version', '3');
            INSERT INTO deliveries (delivery_id, state, claimed_at, ttl_seconds) VALUES ('old', 'claimed', 1.0, 30.0);
            """
        )
        await db.commit()

    store = await SQLiteStore(path).connect()
    try:
        cur = await store._dbp().execute("PRAGMA table_info(deliveries)")  # noqa: SLF001
        columns = {row[1] for row in await cur.fetchall()}
        assert {"obligation_id", "owner_pid", "owner_start", "attempts", "not_before", "recovered", "platform"} <= columns
        old = await store.delivery_row("old")
        assert old is not None and old["state"] == "claimed" and old["attempts"] == 0

        assert await store.create_obligation("d1", "sha-1", "desktop", session_id="s1", content_sha="abc") is True
        assert await store.create_obligation("d1", "sha-1", "desktop", session_id="s1", content_sha="abc") is True
        assert await store.create_obligation("d1", "sha-2", "desktop") is False  # 同 id 异义务不覆盖
        row = await store.delivery_row("d1")
        assert row is not None and row["state"] == "pending" and row["obligation_id"] == "sha-1"
        assert await store.create_obligation("d2", "sha-2", "im") is True
        assert (await store.delivery_row("d2"))["state"] == "undeliverable"
    finally:
        await store.close()


async def test_legacy_claim_and_ack_semantics_stay(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "legacy.db")).connect()
    try:
        assert await store.claim_delivery("legacy", ttl_seconds=100) is True
        assert await store.delivery_state("legacy") == "claimed"
        assert await store.ack_delivery("legacy") is True
        assert await store.delivery_state("legacy") == "acked"
    finally:
        await store.close()


async def test_claim_recovers_expired_attempting_and_abandoned_never_revives(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "claim.db")).connect()
    try:
        await store.create_obligation("d1", "sha-1", "desktop", now=100.0)
        first = await store.claim_obligation(now=100.0, owner_pid=1, owner_start=10.0)
        assert first and first[0]["recovered"] is False and first[0]["attempts"] == 1
        # TTL 过期（30s）→ 崩溃重投带 recovered；attempts 递增
        second = await store.claim_obligation(now=200.0, owner_pid=2, owner_start=20.0)
        assert second and second[0]["recovered"] is True and second[0]["attempts"] == 2

        await store.create_obligation("d2", "sha-2", "http", now=100.0)
        assert await store.finish_delivery("d2", "abandoned") is True
        late = await store.claim_obligation(now=10_000.0, owner_pid=3, owner_start=30.0)
        assert all(item["delivery_id"] != "d2" for item in late)  # abandoned 不选
        assert await store.finish_delivery("d2", "pending") is False  # abandoned 不复活
    finally:
        await store.close()


async def test_sweeps_and_prune_boundaries(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "sweep.db")).connect()
    try:
        await store.create_obligation("d3", "sha-3", "desktop", now=100.0)
        await store.claim_obligation(now=100.0, owner_pid=1, owner_start=10.0)
        assert await store.finish_delivery("d3", "failed", error_class="reconnect", not_before=50.0) is True
        assert await store.pending_retries(now=60.0) == 1
        assert await store.sweep_failed_for_runtime(now=60.0) == 1
        assert (await store.delivery_row("d3"))["state"] == "pending"

        for index in range(510):
            await store.create_obligation(f"a{index}", f"sha-a{index}", "desktop", now=float(index))
            await store.finish_delivery(f"a{index}", "acked")
        await store.create_obligation("live", "sha-live", "desktop")
        removed = await store.prune_deliveries(max_rows=500)
        assert removed == 12  # 512 行 - 500；只删 acked，live 保留
        assert (await store.delivery_row("live"))["state"] == "pending"
    finally:
        await store.close()


class _Registry:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def submit(self, run_id, command, *, source, idempotency_key):  # noqa: ANN001
        self.calls.append(command)

    def unregister(self, run_id: str) -> None:
        return None


class _RaisingStore:
    async def claim_delivery(self, delivery_id: str, ttl_seconds: float = 30.0) -> bool:
        raise RuntimeError("ledger down")

    async def ack_delivery(self, delivery_id: str) -> bool:
        raise RuntimeError("ledger down")


async def test_ledger_failure_never_blocks_report_send() -> None:
    registry = _Registry()
    orchestrator = SubagentOrchestrator(surface=None, bus=None, store=_RaisingStore(), registry=registry)  # type: ignore[arg-type]
    await orchestrator._complete_child("child", "parent", "node", "completed", "done")  # noqa: SLF001
    assert len(registry.calls) == 1 and isinstance(registry.calls[0], ReportChildTerminal)


async def _schedule(store: SQLiteStore, *, due: float = 100.0, interval: float = 60.0, subject: str = "reminder") -> None:
    await store.create_session("s1")
    await store.upsert_schedule("sch-1", "s1", subject, "take a break", interval, due)


async def test_scheduler_fires_only_via_submissions(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "sched.db")).connect()
    try:
        await _schedule(store)
        result = await Scheduler(store).tick(now=100.0)
        assert result == {"fired": 1, "skipped": 0, "held": 0}
        rows = await store.submissions_since("s1", 0)
        assert len(rows) == 1 and rows[0]["source"] == "scheduler" and rows[0]["kind"] == "user_message"
        assert await store.watermark() == 0  # 调度器不 append event_log
        assert (await store.due_schedules(999.0)) == [] or (await store.due_schedules(999.0))[0]["next_run_at"] == 160.0
    finally:
        await store.close()


async def test_scheduler_ownership_is_exclusive(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "owner.db")).connect()
    try:
        await _schedule(store)
        assert await store.acquire_lease("sched:main", "other-owner", 1, ttl_seconds=60) is True
        assert await Scheduler(store).tick(now=100.0) == {"fired": 0, "skipped": 0, "held": 0}
        assert await store.submissions_since("s1", 0) == []
        await store.release_lease("sched:main", "other-owner", 1)
    finally:
        await store.close()


async def test_scheduler_quota_hold_stops_at_boundary(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "quota.db")).connect()
    try:
        await _schedule(store)
        result = await Scheduler(store, quota_remaining=lambda: 0, quota_retry_seconds=500).tick(now=100.0)
        assert result == {"fired": 0, "skipped": 0, "held": 1}
        assert await store.submissions_since("s1", 0) == []
        due = await store.due_schedules(10_000.0)
        assert due and due[0]["next_run_at"] == 600.0  # 停在恢复边界，不补跑
    finally:
        await store.close()


async def test_scheduler_hourly_cap_and_quiet(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "guard.db")).connect()
    try:
        await _schedule(store, interval=1.0)
        scheduler = Scheduler(store, max_per_hour=2)
        assert (await scheduler.tick(now=100.0))["fired"] == 1
        assert (await scheduler.tick(now=101.0))["fired"] == 1
        assert (await scheduler.tick(now=102.0))["skipped"] == 1  # 同会话同主体每小时上限
        assert len(await store.submissions_since("s1", 0)) == 2

        await store.set_session_quiet("s1", "1970-01-01")
        assert (await scheduler.tick(now=200.0))["skipped"] == 1  # 今日静默
        assert len(await store.submissions_since("s1", 0)) == 2
    finally:
        await store.close()


async def test_scheduler_execution_identity_is_visible(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "identity.db")).connect()
    try:
        await _schedule(store)
        seen: list[str | None] = []
        original = store.enqueue_submission

        async def spy(*args, **kwargs):  # noqa: ANN002, ANN003
            seen.append(current_execution_identity())
            return await original(*args, **kwargs)

        store.enqueue_submission = spy  # type: ignore[method-assign]
        await Scheduler(store).tick(now=100.0)
        assert seen == ["sched:sch-1:100.0"]
    finally:
        await store.close()


async def test_logs_totals_and_expand_still_work(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "logs.db")).connect()
    try:
        out = await run_logs_command(store, tmp_path / "logs", run_id=None, totals=True, expand=False)
        assert isinstance(out, str) and out
    finally:
        await store.close()
