"""B3 耐久提交队列：store 级幂等/背压/跨端游标（v3 §4.4；ADR-0013/C2/C16）。"""

from __future__ import annotations

import httpx
import pytest

from questor.contracts.events import Cancel, ResolveApproval, SubmitMessage
from questor.contracts.inbox import InboxStatus
from questor.contracts.state_schema import CancelReason, ContentBlock, Message, Role
from questor.contracts.submissions import (
    MAX_QUEUE_ITEMS,
    SubmissionConflictError,
    SubmissionQueueFullError,
    command_digest,
    command_payload,
)
from questor.kernel.run_control import RunController
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app


def _user(text: str) -> Message:
    return Message(id=f"m-{text}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def _submit(text: str) -> SubmitMessage:
    return SubmitMessage(run_id="run", content=_user(text))


def _enqueue(store: SQLiteStore, session: str, key: str, text: str, *, source: str = "cli"):
    command = _submit(text)
    return store.enqueue_submission(
        session,
        "user_message",
        command_payload(command),
        source=source,
        idem_key=key,
        digest=command_digest(command),
    )


async def test_enqueue_is_idempotent_and_conflict_rejects() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        first = await _enqueue(store, "s1", "k1", "hello")
        duplicate = await _enqueue(store, "s1", "k1", "hello")
        assert first["duplicate"] is False and duplicate["duplicate"] is True
        assert first["change_version"] == duplicate["change_version"]
        with pytest.raises(SubmissionConflictError):
            await _enqueue(store, "s1", "k1", "different")
        assert await store.pending_submission_count("s1") == 1
    finally:
        await store.close()


async def test_queue_full_backpressure_is_explicit() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        for index in range(MAX_QUEUE_ITEMS):
            await _enqueue(store, "s-full", f"k{index}", f"m{index}")
        with pytest.raises(SubmissionQueueFullError):
            await _enqueue(store, "s-full", "overflow", "overflow")
    finally:
        await store.close()


async def test_change_version_is_global_and_monotonic() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        a = await _enqueue(store, "s1", "k1", "a")
        b = await _enqueue(store, "s2", "k1", "b")
        c = await _enqueue(store, "s1", "k2", "c")
        versions = [a["change_version"], b["change_version"], c["change_version"]]
        assert versions == sorted(set(versions)), versions
        rows = await store.submissions_since("s1", 0)
        assert [row["change_version"] for row in rows] == [a["change_version"], c["change_version"]]
        tail = await store.submissions_since("s1", rows[0]["change_version"])
        assert [row["change_version"] for row in tail] == [c["change_version"]]
        assert await store.submissions_since("s1", c["change_version"]) == []
    finally:
        await store.close()


async def test_claim_ack_release_lifecycle() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        await _enqueue(store, "s1", "k1", "first")
        await _enqueue(store, "s1", "k2", "second")
        claimed = await store.claim_submissions("s1", run_id="run-1")
        assert [row["seq_in_session"] for row in claimed] == [1, 2]
        assert all(row["run_id"] == "run-1" for row in claimed)
        assert await store.pending_submission_count("s1") == 2  # deferred 仍在途

        ids = tuple(row["item_id"] for row in claimed)
        assert await store.ack_submissions(ids[:1]) == 1
        assert [row["state"] for row in await store.submissions_since("s1", 0)] == ["consumed", "deferred"]
        assert await store.release_submissions(ids[1:]) == 1
        assert [row["state"] for row in await store.submissions_since("s1", 0)] == ["consumed", "pending"]
        assert await store.trim_consumed_submissions("s1", keep=0) == 1
    finally:
        await store.close()


async def test_cancel_payload_roundtrips_through_canonical_json() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        command = Cancel(run_id="run", reason=CancelReason.USER)
        row = await store.enqueue_submission(
            "s1",
            "cancel",
            command_payload(command),
            source="desktop",
            idem_key="cancel:run",
            digest=command_digest(command),
        )
        assert row["duplicate"] is False
        claimed = await store.claim_submissions("s1")
        assert claimed[0]["payload"]["fields"]["reason"] == "user"
        assert claimed[0]["source"] == "desktop"
    finally:
        await store.close()


async def test_controller_durable_submit_claim_ack() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        run = Run(run_id="run-1")
        controller = RunController(run, queue=store, session_id="s1")
        receipt = await controller.submit(SubmitMessage(run_id="run-1", content=_user("hello")), source="cli", idempotency_key="k1")
        assert receipt.status is InboxStatus.ACCEPTED
        duplicate = await controller.submit(SubmitMessage(run_id="run-1", content=_user("hello")), source="cli", idempotency_key="k1")
        assert duplicate.status is InboxStatus.DUPLICATE
        batch = await controller.next_batch()
        assert len(batch) == 1 and isinstance(batch[0], SubmitMessage)
        assert batch[0].content.content[0].text == "hello"
        await controller.ack(batch)
        assert [row["state"] for row in await store.submissions_since("s1", 0)] == ["consumed"]
        controller.close()
        assert (await controller.submit(Cancel(run_id="run-1", reason=CancelReason.USER), source="cli", idempotency_key="late")).status is InboxStatus.REJECTED_TERMINAL
    finally:
        await store.close()


async def test_durable_queue_survives_controller_restart() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        first = RunController(Run(run_id="run-1"), queue=store, session_id="s1")
        await first.submit(SubmitMessage(run_id="run-1", content=_user("before kill")), source="cli", idempotency_key="k1")
        # 模拟进程 kill：不 ack、不 drain，换一个 controller 从表里重新 claim。
        second = RunController(Run(run_id="run-1"), queue=store, session_id="s1")
        batch = await second.next_batch()
        assert len(batch) == 1 and batch[0].content.content[0].text == "before kill"
    finally:
        await store.close()


async def test_wait_for_releases_unmatched_and_returns_match() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        controller = RunController(Run(run_id="run-1"), queue=store, session_id="s1")
        await controller.submit(Cancel(run_id="run-1", reason=CancelReason.USER), source="http", idempotency_key="k-cancel")
        approval = ResolveApproval(run_id="run-1", request_id="apr-1", decision="allow", decided_by="http_client")

        async def submit_later() -> None:
            import asyncio

            await asyncio.sleep(0.05)
            await controller.submit(approval, source="http", idempotency_key="apr-1")

        import asyncio

        task = asyncio.create_task(submit_later())
        received = await controller.wait_for(lambda command: isinstance(command, ResolveApproval), timeout=2)
        await task
        assert received == approval
        await controller.ack_one(received)
        # 不匹配的 Cancel 已 release 回 pending，仍可被下一次 next_batch 取到。
        batch = await controller.next_batch()
        assert len(batch) == 1 and isinstance(batch[0], Cancel)
    finally:
        await store.close()


async def test_http_session_submissions_after_version(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "queue.db")).connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path, store=store), store)
        app = create_app(server)
        first = await _enqueue(store, "s1", "k1", "a")
        second = await _enqueue(store, "s1", "k2", "b")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://svc", trust_env=False) as client:
            response = await client.get("/sessions/s1/submissions", params={"after_version": 0})
            assert response.status_code == 200
            body = response.json()
            assert [item["change_version"] for item in body["items"]] == [first["change_version"], second["change_version"]]
            assert body["head"] == second["change_version"]

            tail = await client.get("/sessions/s1/submissions", params={"after_version": first["change_version"]})
            assert [item["change_version"] for item in tail.json()["items"]] == [second["change_version"]]
    finally:
        await store.close()
