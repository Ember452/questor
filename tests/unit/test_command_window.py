"""B2 命令窗口：store 级幂等/digest 冲突/裁剪（v3 §4.3）。"""

from __future__ import annotations

import pytest

from questor.contracts.submissions import CommandDigestConflict
from questor.providers.store_sqlite import SQLiteStore


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
