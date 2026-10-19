"""P10 TB2/TB4（TDD）—— ``questor logs`` 只读消费命令 + session usage 读侧聚合。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from questor.contracts.events import EventType
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.logs import read_bypass_rows, run_logs_command, session_totals


def test_session_totals_sums_run_completed_usage() -> None:
    events = [
        {"type": EventType.RUN_COMPLETED, "data": {"usage": {"input_tokens": 10, "output_tokens": 5}}},
        {"type": EventType.RUN_COMPLETED, "data": {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}},
        {"type": EventType.RUN_FAILED, "data": {}},  # 非终态完成 → 不计
    ]
    agg = session_totals(events)
    assert agg["runs_completed"] == 2
    assert agg["input_tokens"] == 13
    assert agg["output_tokens"] == 7
    assert agg["total_tokens"] == 20


def test_session_totals_ignores_usage_delta_never_persisted() -> None:
    # usage_delta 从不入库/发射；即便出现也不得作为聚合源（MAJ-4）——只认 run_completed。
    events = [{"type": EventType.USAGE_DELTA, "data": {"total_tokens": 999}}]
    assert session_totals(events)["total_tokens"] == 0


def test_read_bypass_rows_counts_malformed_and_filters_run(tmp_path: Path) -> None:
    (tmp_path / "questor-20260101.jsonl").write_text(
        '{"source":"event","context":{"run_id":"r1"},"fields":{"seq":1},"level":"INFO","msg":"a"}\n'
        "NOT JSON\n"
        '{"source":"event","context":{"run_id":"r2"},"fields":{"seq":2},"level":"WARN","msg":"b"}\n',
        encoding="utf-8",
    )
    rows, malformed = read_bypass_rows(tmp_path, run_id="r1")
    assert malformed == 1  # 坏行跳过并计数、不崩
    assert len(rows) == 1 and rows[0]["msg"] == "a"


async def test_run_logs_command_totals_and_readonly(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        # 手工落两条 run_completed 事件到两个 run（经 append，非本命令所为）
        await store.append("runA", (_completed("runA", 1, {"input_tokens": 7, "output_tokens": 3}),))
        await store.append("runB", (_completed("runB", 1, {"input_tokens": 1, "output_tokens": 1}),))
        seq_before = await store.sequence_head("runA")
        out = await run_logs_command(store, tmp_path, totals=True)
        assert "runs_completed=2" in out
        assert "input_tokens=8" in out
        assert "total_tokens=12" in out
        # 只读：跑命令后 head 不变（绝不新增事件/改状态）
        assert await store.sequence_head("runA") == seq_before
    finally:
        await store.close()


def _completed(run_id: str, seq: int, usage: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "seq": seq, "run_id": run_id, "type": EventType.RUN_COMPLETED, "data": {"usage": usage, "exit_reason": "answered"}}
