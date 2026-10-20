"""B3 耐久提交队列：store 级幂等/背压/跨端游标（v3 §4.4；ADR-0013/C2/C16）。"""

from __future__ import annotations

import pytest

from questor.contracts.events import Cancel, SubmitMessage
from questor.contracts.state_schema import CancelReason, ContentBlock, Message, Role
from questor.contracts.submissions import (
    MAX_QUEUE_ITEMS,
    SubmissionConflictError,
    SubmissionQueueFullError,
    command_digest,
    command_payload,
)
from questor.providers.store_sqlite import SQLiteStore


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
