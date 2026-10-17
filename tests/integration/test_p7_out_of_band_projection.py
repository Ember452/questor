"""P7 T2 收口 canary：sidecar（EventServer）路径的带外事件投影 = **每条 Envelope 恰一行**，
与并发 SSE 订阅者数量无关——真文件面（读按日 JSONL），非 `LogEntry` 构造（pitfalls#1 纪律③）。

这条正面收 `plan/05 §0.4`/P5 审计 §6 的缺口：HTTP sidecar 路径此前**完全不投带外日志**（`stream()` 只出
SSE 帧）。T2 后，组合根给 `EventServer` 的 bus 挂**一条** `log_envelope` observer（`emit` 时触发、与订阅者
无关），故：开 2 个并发 `/events` 订阅者跑同一 run，主干日志里每条 seq 仍**恰一行**（若回到"逐消费者各投"，
两订阅者会翻倍 → 本用例判红）。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from questor.contracts.events import Envelope, EventType
from questor.observability import configure as log_configure
from questor.observability import exporter as log_exporter
from questor.observability import pipeline as log_pipeline
from questor.observability.entry import LogLevel
from questor.providers.fake import EchoProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer


@pytest.fixture
def clean_logging() -> Iterator[None]:
    """快照/还原进程级日志装配，避免残留桥/文件 sink 泄进后续用例（同 test_log_correlation 口径）。"""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_registry = list(log_exporter._registry)  # noqa: SLF001
    saved_state = log_configure._state  # noqa: SLF001
    log_pipeline.reset()
    log_configure._state = None
    try:
        yield
    finally:
        log_configure._teardown()  # noqa: SLF001
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        log_exporter._registry[:] = saved_registry  # noqa: SLF001
        log_configure._state = saved_state  # noqa: SLF001
        log_pipeline.reset()


def _event_rows(log_dir: Path, run_id: str) -> list[dict]:
    path = log_dir / f"questor-{date.today():%Y%m%d}.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("source") == "event" and r.get("context", {}).get("run_id") == run_id]


async def _drain(stream_aiter, sink: list) -> None:
    async for frame in stream_aiter:
        sink.append(frame["event"])


async def _drive_sidecar_projection(tmp_path: Path) -> None:
    log_configure.configure_logging(console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG, log_dir=tmp_path)
    store = await SQLiteStore(str(tmp_path / "oob.db")).connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider()), store)
        run_id = "run_oob"
        # 两个并发 SSE 订阅者（模拟多 surface 消费者）：若投影是"逐消费者"，两订阅者会让带外行翻倍。
        a: list = []
        b: list = []
        task_a = asyncio.create_task(_drain(server.stream(run_id, 0), a))
        task_b = asyncio.create_task(_drain(server.stream(run_id, 0), b))
        await asyncio.sleep(0)  # 让两订阅者先把队列挂上（先订阅后 emit）

        for env in [
            Envelope(v=1, seq=1, run_id=run_id, type=EventType.RUN_STARTED, data={"run_id": run_id}),
            Envelope(v=1, seq=2, run_id=run_id, type=EventType.TOOL_COMPLETED, data={"tool_call_id": "tc", "status": "success"}),
            Envelope(v=1, seq=3, run_id=run_id, type=EventType.MESSAGE_COMPLETED, data={"message_id": "m"}),
            Envelope(v=1, seq=4, run_id=run_id, type=EventType.RUN_COMPLETED, data={"usage": {}, "exit_reason": "answered"}),
        ]:
            await server.bus.emit(env)

        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=15)
        log_pipeline.flush()
        # 两订阅者都应收到 4 帧（含终态），证明"事件确实扇出到了多个消费者"——即翻倍风险的现场。
        assert a == ["run_started", "tool_completed", "message_completed", "run_completed"], a
        assert b == a, b
    finally:
        await store.close()


def test_sidecar_projects_each_event_once_across_two_subscribers(clean_logging: None, tmp_path: Path) -> None:
    asyncio.run(_drive_sidecar_projection(tmp_path))
    rows = _event_rows(tmp_path, "run_oob")
    assert rows, "sidecar 路径应产生带外事件行（收口 plan/05 §0.4 缺口：此前完全不投）"
    seqs = sorted(r["fields"]["seq"] for r in rows if "seq" in r.get("fields", {}))
    # 4 条对外事件（run_started/tool_completed/message_completed/run_completed）各恰一行；两订阅者不翻倍（应为 4 非 8）。
    assert seqs == [1, 2, 3, 4], f"每条 Envelope 应恰投一行带外日志（两订阅者不增份），实得 seq 序列 {seqs}"
