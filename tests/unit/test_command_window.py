"""B2 命令窗口：store 级幂等/digest 冲突/裁剪（v3 §4.3）。"""

from __future__ import annotations

import pytest

from questor.contracts.events import RecordToolResult, SubmitMessage
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.contracts.submissions import CommandDigestConflict
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.transition import apply, reset_idempotency_window


async def test_record_command_is_idempotent_and_conflict_rejects() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        first = await store.record_command(
            "run-1", 1, "submit_message", '{"x":1}', source="loop", idem_key="k1", digest="d1"
        )
        duplicate = await store.record_command(
            "run-1", 1, "submit_message", '{"x":1}', source="loop", idem_key="k1", digest="d1"
        )
        assert first["duplicate"] is False and duplicate["duplicate"] is True
        assert duplicate["cseq"] == first["cseq"]
        with pytest.raises(CommandDigestConflict):
            await store.record_command("run-1", 2, "advance_turn", "{}", source="loop", idem_key="k1", digest="d2")
        rows = await store.command_window_rows(run_id="run-1")
        assert len(rows) == 1 and rows[0]["accepted"] is True
    finally:
        await store.close()


async def test_command_window_rows_filter_by_run_and_session() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        await store.record_command("run-a", 1, "submit_message", "{}", source="loop", idem_key="a", digest="da", session_id="s1")
        await store.record_command("run-b", 1, "submit_message", "{}", source="loop", idem_key="b", digest="db", session_id="s2")
        assert [row["run_id"] for row in await store.command_window_rows(session_id="s1")] == ["run-a"]
        assert [row["run_id"] for row in await store.command_window_rows(limit=1)] == ["run-a"]
    finally:
        await store.close()


def test_apply_marks_rejected_command_as_not_accepted() -> None:
    reset_idempotency_window()
    run = Run(run_id="run-reject")
    applied = apply(
        None,
        run,
        RecordToolResult(run_id="run-reject", tool_call_id="missing", status="error", result="x"),
        source="test",
        idempotency_key="k1",
    )
    assert applied.accepted is False
    new_run, events = applied
    assert new_run.seq == run.seq + 1 and events[0].type == "warning"


async def test_loop_records_accepted_commands_in_window(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "window.db")).connect()
    try:
        provider = ScriptedProvider([[StreamChunk(kind="text", text="ok"), StreamChunk(kind="finish", finish_reason="stop")]])
        loop = DefaultTurnLoop(
            provider=provider,
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(store),
            tool_for=lambda _name: None,
            store=store,
            workspace_root=tmp_path,
        )
        controller = RunController(Run(run_id="run-win", budget=Budget(max_turns=3)), queue=store, session_id="s1")
        message = Message(id="m", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)
        await controller.submit(SubmitMessage(run_id="run-win", content=message), source="cli", idempotency_key="u1")
        final = await loop.drive_controller(controller)
        assert final.status.value == "completed"
        rows = await store.command_window_rows(run_id="run-win")
        types = [row["type"] for row in rows]
        assert "submit_message" in types and "record_turn_completed" in types and "finalize_run" in types
        assert all(row["accepted"] for row in rows)
    finally:
        await store.close()


async def _bulk_window(store: SQLiteStore, run_id: str, session_id: str, start: int, count: int) -> None:
    db = store._dbp()  # noqa: SLF001 - 测试批量造数
    await db.execute("BEGIN")
    await db.executemany(
        "INSERT INTO command_window (run_id, session_id, seq, type, payload, source, idem_key, digest, accepted, ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (run_id, session_id, start + i, "submit_message", "{}", "loop", f"{run_id}-{start + i}", f"d{start + i}", 1, "2026-01-01T00:00:00+00:00")
            for i in range(count)
        ],
    )
    await db.commit()


async def test_trim_keeps_absorbed_tail_and_respects_global_cap(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "trim.db")).connect()
    try:
        await store.create_session("s1")
        await _bulk_window(store, "run-trim", "s1", 1, 1000)
        await store.advance_last_consolidated("s1", 1000)
        await store.trim_command_window("s1")
        rows = await store.command_window_rows(session_id="s1")
        assert len(rows) == 512
        assert all(row["seq"] <= 1000 for row in rows)

        await _bulk_window(store, "run-old", "s1", 1, 10050)
        await _bulk_window(store, "run-new", "s1", 1, 10000)
        await store.trim_command_window("s1")
        remaining = await store.command_window_rows()
        assert len(remaining) <= 20000
        assert not any(row["run_id"] == "run-old" for row in remaining)  # 最旧 run 整批 drop
    finally:
        await store.close()


async def test_fold_mode_default_and_validation(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "fold.db")).connect()
    try:
        assert await store.fold_mode("s1") == "v1"
        assert await store.set_fold_mode("s1", "legacy") == "legacy"
        assert await store.fold_mode("s1") == "legacy"
        with pytest.raises(ValueError):
            await store.set_fold_mode("s1", "v9")
    finally:
        await store.close()
