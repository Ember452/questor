"""P9 canary（承 pitfalls #5 / ADR-0033 / plan §4 T10）：带 CLI+SSE+OpenAI **三**消费者时，
带外事件投影仍**每条 Envelope 恰一行**——证明 OpenAI 兼容面复用 bus 级唯一 observer、
**不逐消费者各投 `log_envelope`**（回到逐消费者投影 → 三订阅者翻倍 → 本用例判红）。

真文件面（读按日 JSONL），非 `LogEntry` 构造（pitfalls#1 纪律③）。这是回归护栏：新增/改动
OpenAI 面若偷偷加自带投影，本用例会红。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
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
from questor.surfaces.openai_compat import project_openai_stream

_RUN_ID = "run_oob_p9"


@pytest.fixture
def clean_logging() -> Iterator[None]:
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
    rows: list[dict] = []
    for path in sorted(log_dir.glob("questor-*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("source") == "event" and r.get("context", {}).get("run_id") == run_id]


async def _drain_sse(stream_aiter, sink: list) -> None:
    # SSE 帧是 {id,event,data}；取事件名。
    async for frame in stream_aiter:
        sink.append(frame["event"])


async def _drain_raw(stream_aiter, sink: list) -> None:
    # OpenAI 投影产出 chunk dict 或 "[DONE]" 哨兵，原样收集。
    async for frame in stream_aiter:
        sink.append(frame)


async def _drive(tmp_path: Path) -> None:
    log_configure.configure_logging(console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG, log_dir=tmp_path)
    store = await SQLiteStore(str(tmp_path / "oob.db")).connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider()), store)
        a: list = []
        b: list = []
        oai: list = []
        task_a = asyncio.create_task(_drain_sse(server.stream(_RUN_ID, 0), a))
        task_b = asyncio.create_task(_drain_sse(server.stream(_RUN_ID, 0), b))
        # 第三消费者 = OpenAI 投影订阅者（只读订总线，不另挂带外投影）。
        openai_gen = project_openai_stream(server.bus.subscribe(_RUN_ID, 0), completion_id="chatcmpl-x", model="questor", created=1)
        task_oai = asyncio.create_task(_drain_raw(openai_gen, oai))
        await asyncio.sleep(0)  # 三订阅者先把队列挂上（先订阅后 emit）

        for env in [
            Envelope(v=1, seq=1, run_id=_RUN_ID, type=EventType.RUN_STARTED, data={"run_id": _RUN_ID}),
            Envelope(v=1, seq=2, run_id=_RUN_ID, type=EventType.TOOL_COMPLETED, data={"tool_call_id": "tc", "status": "success"}),
            Envelope(v=1, seq=3, run_id=_RUN_ID, type=EventType.MESSAGE_COMPLETED, data={"message_id": "m"}),
            Envelope(v=1, seq=4, run_id=_RUN_ID, type=EventType.RUN_COMPLETED, data={"usage": {}, "exit_reason": "answered"}),
        ]:
            await server.bus.emit(env)

        await asyncio.wait_for(asyncio.gather(task_a, task_b, task_oai), timeout=15)
        log_pipeline.flush()
        assert [x for x in a if x != "stream_end"] == ["run_started", "tool_completed", "message_completed", "run_completed"], a
        # OpenAI 消费者确实收到投影帧并以 [DONE] 终结（不是空订阅）。
        assert oai and oai[-1] == "[DONE]", oai
    finally:
        await store.close()


def test_three_consumers_project_each_event_once(clean_logging: None, tmp_path: Path) -> None:
    asyncio.run(_drive(tmp_path))
    rows = _event_rows(tmp_path, _RUN_ID)
    assert rows, "带外事件行应产生（三消费者场景）"
    seqs = sorted(r["fields"]["seq"] for r in rows if "seq" in r.get("fields", {}))
    # 4 条对外事件各恰一行；三消费者（2 SSE + 1 OpenAI）绝不翻倍（应为 4 非 8/12）。
    assert seqs == [1, 2, 3, 4], f"每条 Envelope 应恰投一行带外日志（三消费者不增份），实得 seq 序列 {seqs}"
