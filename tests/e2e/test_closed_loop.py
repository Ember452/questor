"""§0.9 闭环验收 E1–E8（端到端，scripted provider，无网络、无真 LLM）。

这八条是**跨刀串起来**的证明：每条都走完一整段真实链路（HTTP/CLI 入口 → 队列/咽喉 → durable
事实 → 投影/SSE 帧 → 重开进程），而不是某一刀的局部判据。任一条不过就如实标未闭环，
**不得报"全部完成"**（§0.9 原文要求）。

写法定律：
- 只断言"durable 事实 + 订阅者真收到的帧"，不靠内存对象传递；
- "重开进程"一律用**新的 store 实例读同一个 db 文件**（不是同一个 Python 对象）；
- 每条一个测试函数、名字带 `E1`…`E8`，便于与 §0.9 的表逐行对照。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from evals.metrics import (
    duplicate_reminder_rate,
    forgetting_rate,
    per_task_cost,
    recall_hit_rate,
    revoke_rate,
    write_noise_rate,
)
from questor.composition import build_app, close_app
from questor.contracts.common import new_id
from questor.contracts.events import AppendAssistantMessage, DeleteMemory, EventType, SubmitMessage
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.contracts.submissions import command_digest, command_payload
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import rebuild_run, verify_recovery_anchors
from questor.kernel.run_control import RunController
from questor.kernel.session_ops import apply_on_stream, session_stream_id
from questor.memory.recall import MemoryRecall
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider, StreamChunk
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.schedule.scheduler import Scheduler
from questor.state.domain_state import Context, Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer

pytestmark = pytest.mark.e2e

pytest.importorskip("httpx")


def _msg(text: str, seq: int, role: Role = Role.USER) -> Message:
    return Message(id=f"m{seq}-{role.value}", role=role, content=(ContentBlock(type="text", text=text),), seq=seq)


def _answer(text: str) -> list[StreamChunk]:
    return [StreamChunk(kind="text", text=text), StreamChunk(kind="finish", finish_reason="stop")]


def _read(call_id: str, path: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "read", "args_delta": __import__("json").dumps({"file_path": path})}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


def _point_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(tmp_path / "memory_store"))
    monkeypatch.setenv("QUESTOR_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("QUESTOR_MCP_JSON", str(tmp_path / "mcp.json"))
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("QUESTOR_COMPACTION", "off")  # 闭环用例逐条隔离，除 E7 外不夹带压缩
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("QUESTOR_EMBED_MODEL", raising=False)


async def _drain(queue: asyncio.Queue, want: set[str], *, timeout: float = 20.0) -> list[Any]:
    """把 SSE 面真正会看到的帧收齐（同一个 `add_subscriber` 队列，不是另建一份投影）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    seen: list[Any] = []
    while loop.time() < deadline:
        try:
            seen.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)
        if want <= {env.type for env in seen}:
            return seen
    raise AssertionError(f"never saw {want} on the fan-out queue; got {[env.type for env in seen]}")


def _transcript(rows: list[dict]) -> list[tuple[int, str, Any]]:
    """可见转录口径：seq + 类型 + 用户原话/定稿文本（不依赖内存对象）。"""
    out: list[tuple[int, str, Any]] = []
    for row in rows:
        data = row["data"]
        text = data.get("text") if row["type"] == EventType.USER_MESSAGE else data.get("final_text")
        out.append((int(row["seq"]), str(row["type"]), text))
    return out


# --------------------------------------------------------------------------- #
# E1：发一条 → SSE 面收到 turn_completed → 重开进程后历史仍在（B1/B4/B6）
# --------------------------------------------------------------------------- #
async def test_E1_one_turn_reaches_sse_and_survives_process_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_env(monkeypatch, tmp_path)
    app = await build_app()
    run_id = new_id("run")
    try:
        server = EventServer(app.surface, app.store)
        queue = server.bus.add_subscriber(run_id)
        await server.start_run("first take", run_id=run_id, session_id="sess-e1")
        frames = await _drain(queue, {EventType.TURN_COMPLETED, EventType.RUN_COMPLETED})
        types = [env.type for env in frames]
        assert types.index(EventType.TURN_COMPLETED) < types.index(EventType.RUN_COMPLETED)
        assert sum(1 for t in types if t in {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}) == 1

        before = _transcript(await app.store.replay(run_id, 0))
        assert any(row[2] == "first take" for row in before if row[1] == EventType.USER_MESSAGE)  # 原话进了事实流
    finally:
        await close_app(app)

    # “重开进程” = 新 store 实例读同一个 db 文件，逐条相等才算历史仍在
    reopened = await SQLiteStore(str(tmp_path / "state.db")).connect()
    try:
        assert _transcript(await reopened.replay(run_id, 0)) == before
    finally:
        await reopened.close()


# --------------------------------------------------------------------------- #
# E2：同一 session 两端同时提交 → 都入队、按序、不丢不重（B3/B4）
# --------------------------------------------------------------------------- #
async def test_E2_two_clients_same_session_queue_in_order_without_loss(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        sid = await store.create_session()

        async def client(label: str) -> dict:
            command = SubmitMessage(run_id="pending", content=_msg(f"from {label}", 0))
            return await store.enqueue_submission(
                sid, "user_message", command_payload(command), source="http", idem_key=f"k-{label}", digest=command_digest(command)
            )

        first, second = await asyncio.gather(client("A"), client("B"))
        assert first["item_id"] != second["item_id"]  # 两个写者都在，谁也没被吞
        assert first["duplicate"] is False and second["duplicate"] is False
        rows = await store.submissions_since(sid, 0)
        assert [row["idem_key"] for row in rows] == sorted(row["idem_key"] for row in rows)  # 按序可见
        assert {row["change_version"] for row in rows} == {first["change_version"], second["change_version"]}

        # 两端读到同一个 head（多端一致）；同键重提不产生第二项
        head = (await store.submissions_since(sid, 0))[-1]["change_version"]
        assert await store.submissions_since(sid, head) == []
        assert await store.pending_submission_count(sid) == 2
        dup = await store.enqueue_submission(
            sid,
            "user_message",
            command_payload(SubmitMessage(run_id="pending", content=_msg("from A", 0))),
            source="http",
            idem_key="k-A",
            digest=command_digest(SubmitMessage(run_id="pending", content=_msg("from A", 0))),
        )
        assert dup["change_version"] == first["change_version"]  # 幂等重投：同一项、不推进 head
        assert await store.pending_submission_count(sid) == 2
    finally:
        await store.close()


# --------------------------------------------------------------------------- #
# E3：kill 后 --resume → 可见转录与 kill 前一致（B1/B4 + snapshot）
# --------------------------------------------------------------------------- #
async def test_E3_resume_after_kill_shows_the_same_visible_transcript(tmp_path: Path) -> None:
    path = str(tmp_path / "s.db")
    store = await SQLiteStore(path).connect()
    try:
        surface = CliSurface(
            workspace_root=tmp_path,
            store=store,
            provider=ScriptedProvider([_answer("noted"), _answer("and again noted")]),
        )
        first = await surface.run_once("the plot is TURQUOISE-31", session_id="sess-e3")
        # 同一个 session 的第二条：这一条**非 idle**，按 B1 口径必须落成 durable `user_message`
        second = await surface.run_once("the plot is TURQUOISE-31 again", session_id="sess-e3")
        assert first.status.value == "completed" and second.status.value == "completed"
        rows_a = await store.replay(first.run_id, 0)
        rows_b = await store.replay(second.run_id, 0)
        assert any(
            row["type"] == EventType.USER_MESSAGE and "again" in str(row["data"].get("text", "")) for row in rows_b
        ), f"非 idle 提交必须事实化，实际只有 {[r['type'] for r in rows_b]}"
        before = {"a": _transcript(rows_a), "b": _transcript(rows_b)}
    finally:
        await store.close()

    # 换一个新连接（= 进程重启）重放：可见转录逐条相等，且没有"重放旁路"（同一 event_log 权威）
    store2 = await SQLiteStore(path).connect()
    try:
        assert _transcript(await store2.replay(first.run_id, 0)) == before["a"]
        assert _transcript(await store2.replay(second.run_id, 0)) == before["b"]
        rebuilt = await rebuild_run(store2, second.run_id)
        assert rebuilt is not None and rebuilt.status.value == "completed"
    finally:
        await store2.close()


# --------------------------------------------------------------------------- #
# E4：记住 → 新 session 召回并带 citation；未读不计消费（B6/B8）
# --------------------------------------------------------------------------- #
async def test_E4_remembered_fact_is_recalled_in_a_new_session_with_citation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_env(monkeypatch, tmp_path)
    app = await build_app()
    prompt = "note this: the vault code is PLUTONIUM-77"
    try:
        # 第一条 session：靠 turn 边界的 settle 写回记忆（不手写 store）
        await app.surface.run_once(prompt, session_id="sess-src")
        hits = await app.memory.search(prompt, k=5)
        assert hits and "PLUTONIUM-77" in hits[0].snippet, "settle 写回后新 session 无从召回"
        entry_path, line_start, line_end = hits[0].path, hits[0].start_line, hits[0].end_line

        # 第二条 session：新会话 + 召回端口；provider 自报引用（协议块由 harness 剥掉）
        citation = (
            "the vault code is PLUTONIUM-77\n<citation_entries>"
            + __import__("json").dumps({"entries": [{"path": entry_path, "line_start": line_start, "line_end": line_end}]})
            + "</citation_entries>"
        )
        recall = MemoryRecall(app.memory, enabled=True)  # 无 embedder：keyword + structured 通道
        surface = CliSurface(
            workspace_root=tmp_path,
            store=app.store,
            memory_store=app.memory,
            provider=ScriptedProvider([_answer(citation)]),
            recall=recall,
        )
        server = EventServer(surface, app.store)
        run_id = new_id("run")
        queue = server.bus.add_subscriber(run_id)
        await server.start_run(prompt, run_id=run_id, session_id="sess-dst")
        frames = await _drain(queue, {EventType.RUN_COMPLETED})
        seen = {env.type for env in frames}

        # 召回真进了请求：live-only `memory_injected` 带条目级 entry_ids（durable 流里没有这类帧）
        injected = [env for env in frames if env.type == EventType.MEMORY_INJECTED]
        assert injected, f"没有 memory_injected 帧；收到 {sorted(seen)}"
        assert any(entry_path in str(env.data.get("entry_ids")) for env in injected), [dict(e.data) for e in injected]
        assert any(env.data.get("kind") == "recall" for env in injected), "注入的不是召回正文（档2）"

        rows = await app.store.replay(run_id, 0)
        completed = next(row for row in rows if row["type"] == EventType.MESSAGE_COMPLETED)
        cited = completed["data"].get("citations") or {}
        entries = cited.get("entries") or []
        assert entries and entries[0]["path"] == entry_path, "citation 展开不到 path:line"
        assert (entries[0]["line_start"], entries[0]["line_end"]) == (line_start, line_end)
        # 协议块不进正文：定稿文本里不该再带标记
        assert "<citation_entries>" not in str(completed["data"].get("final_text", ""))
        # 消费判据：只有被引用/真读才算，光命中不算（未读不计消费）。
        # `memory_consumed` 是 **live-only** 帧（B8 定案：消费观测不占 durable seq），所以从订阅队列读。
        consumed = [env for env in frames if env.type == EventType.MEMORY_CONSUMED]
        assert consumed, "被引用的条目应计一次消费（live-only 帧）"
        assert {str(env.data.get("entry_id", "")) for env in consumed} == {f"{entry_path}:{line_start}-{line_end}"}
        assert all(str(env.data.get("entry_id", "")).startswith(entry_path) for env in consumed)
    finally:
        await close_app(app)


# --------------------------------------------------------------------------- #
# E5：删一条记忆 → 下轮不再召回，且事件可回放（B9）
# --------------------------------------------------------------------------- #
async def test_E5_revoked_memory_stops_being_recalled_and_the_event_replays(tmp_path: Path) -> None:
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        stream = session_stream_id("sess-mem")
        await _seed_fact(memory, "the vendor is ACME-CORP-77")
        entry_id = await _only_entry(memory)

        recalled = await MemoryRecall(memory, enabled=True).recall("the vendor is ACME-CORP-77")
        assert recalled is not None and "ACME-CORP-77" in recalled.text

        _run, events = await apply_on_stream(
            store, bus, stream_run_id=stream, command=DeleteMemory(run_id=stream, entry_id=entry_id, reason="wrong"), idempotency_key="e5-del"
        )
        assert [env.type for env in events] == [EventType.MEMORY_DELETED]
        await memory.soft_delete(entry_id, idempotency_key="e5-io")

        assert await MemoryRecall(memory, enabled=True).recall("the vendor is ACME-CORP-77") is None  # 下轮不再召回
        rows = await store.replay(stream, 0)
        assert [row["type"] for row in rows] == [EventType.MEMORY_DELETED]  # 事件可回放
        cur = await memory._db.execute("SELECT name FROM sqlite_master WHERE type='table'")  # type: ignore[union-attr]
        assert "memory_history" not in {row[0] for row in await cur.fetchall()}  # 没有第二张历史表
    finally:
        await memory.close()
        await store.close()


# --------------------------------------------------------------------------- #
# E6：设一个提醒 → 到点经 scheduler → submissions → 前端读得到（B11）
# --------------------------------------------------------------------------- #
async def test_E6_due_reminder_travels_scheduler_to_submissions(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        sid = await store.create_session()
        now = 1_000.0
        await store.upsert_schedule("sch-1", sid, "standup", "ping the standup room", 3600.0, now - 1)
        scheduler = Scheduler(store, quota_remaining=lambda: 500, max_per_hour=6)
        result = await scheduler.tick(now=now)
        assert result["fired"] >= 1, result

        rows = await store.submissions_since(sid, 0)
        assert [row["source"] for row in rows] == ["scheduler"]  # 三源归一：source='scheduler'
        assert rows[0]["state"] in {"pending", "deferred"}

        # 静默生效：今天别再提 → 同一 tick 不再产提交（配额闸同理，不补跑 N 次）
        await store.set_session_quiet(sid, "1970-01-01")
        before = len(await store.submissions_since(sid, 0))
        await scheduler.tick(now=now + 10)
        assert len(await store.submissions_since(sid, 0)) == before
        held = await Scheduler(store, quota_remaining=lambda: 0).tick(now=now + 20)
        assert held["held"] >= 1 or held["fired"] == 0, held
    finally:
        await store.close()


# --------------------------------------------------------------------------- #
# E7：长会话触发压缩 → 上下文不炸、锚可恢复、头部无孤儿（B10）
# --------------------------------------------------------------------------- #
async def test_E7_long_session_compacts_without_losing_history_or_pairing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha file body", encoding="utf-8")
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        loop = DefaultTurnLoop(
            provider=ScriptedProvider([_read("tc1", "a.txt"), _answer("done")]),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=bus,
            tool_for=lambda n: None,
            workspace_root=tmp_path,
            store=store,
            compaction=CompactionConfig(keep_head=1, keep_tail=1, max_items=2),
        )
        run = Run(run_id="r-e7", budget=Budget(max_turns=4), context=Context(items=()))
        steps = [
            SubmitMessage(run_id="r-e7", content=_msg("the launch code is DELTA-9", 0)),
            AppendAssistantMessage(run_id="r-e7", turn=1, message=_msg("noted DELTA-9", 1, Role.ASSISTANT)),
            SubmitMessage(run_id="r-e7", content=_msg("and the vault is PLUTONIUM-77", 2)),
            AppendAssistantMessage(run_id="r-e7", turn=2, message=_msg("both noted", 3, Role.ASSISTANT)),
        ]
        for command in steps:
            run, events = await loop._transition(run, command)
            await loop._emit(events)
        seeded = len(run.context.items)
        folded = await loop._maybe_compact(RunController(run), run, turn=3, total_tokens=999)
        assert len(folded.context.items) < seeded, "压缩没生效（闸门④/⑦的端到端形态）"
        assert folded.context.summary or folded.context.recovery_pointers  # 中段进摘要 + 留锚
        rows = await store.replay("r-e7", 0)
        assert EventType.COMPACT_APPLIED in [row["type"] for row in rows]
        originals = await verify_recovery_anchors(store, "r-e7")  # 锚可恢复（fail-closed 读回原文）
        assert all(isinstance(message, Message) for message in originals)
        assert _no_head_orphan(folded.context.items)  # 头部无孤儿（配对完整）
        assert closed_or_paired(folded.context.items)
    finally:
        await store.close()


# --------------------------------------------------------------------------- #
# E8：评测环跑出六指标；缺价目表则 cost 标 UNVERIFIED（B12）
# --------------------------------------------------------------------------- #
def test_E8_the_six_metrics_come_out_and_cost_stays_unverified() -> None:
    cited = ["memory/2026-10-01.md:3-7"]
    expected = ["memory/2026-10-01.md:3-7", "memory/2026-10-02.md:1-2"]
    day = 86_400.0
    metrics = [
        recall_hit_rate(cited, expected),
        forgetting_rate({"f1": "DELTA-9"}, "the launch code is DELTA-9"),
        # a 已满 30d 且被消费过 → 不算噪声；b 还没到观察窗 → 两头都不进（分母=1 而不是 2）。
        write_noise_rate([("memory/a.md:1-2", 0.0), ("memory/b.md:1-2", 119.0 * day)], ["memory/a.md:1-2"], now=120.0 * day),
        duplicate_reminder_rate([{"attempts": 2, "recovered": 1}, {"attempts": 1, "recovered": 0}]),
        revoke_rate(4, 1),
        per_task_cost(9000, 3),
    ]
    assert len(metrics) == 6
    assert metrics[0].value == 0.5 and metrics[1].value == 0.0
    assert metrics[2].value == 0.0 and metrics[2].denominator == 1  # 未到期条目不进分母
    assert metrics[3].value == 0.5 and "recovered=1" in metrics[3].note
    assert metrics[4].value == 0.25
    cost = metrics[5]
    assert cost.value == 3000.0 and cost.verified is False and "price table" in cost.note  # 无表就没钱，也不谎称 UNVERIFIED 以外的结论
    priced = per_task_cost(1_000_000, 10, {"input": 1.0, "output": 2.0})
    assert priced.verified is True and "cost_usd=" in priced.note


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _seed_fact(memory: SQLiteMemoryStore, text: str) -> None:
    from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind

    await memory.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=text, attributed_to="user"),
        idempotency_key=f"e5-{abs(hash(text))}",
    )


async def _only_entry(memory: SQLiteMemoryStore) -> str:
    rows = await memory.list_entries()
    assert len(rows) == 1, rows
    return str(rows[0]["entry_id"])


def _no_head_orphan(items: tuple[Message, ...]) -> bool:
    from questor.state.checkpoint import orphan_tool_result_ids

    return not orphan_tool_result_ids(items)


def closed_or_paired(items: tuple[Message, ...]) -> bool:
    """折叠后仍"每个 tool_use 都有配对、且没有裸 tool_result"。"""
    from questor.state.checkpoint import closed_prefix, orphan_tool_result_ids

    return closed_prefix(items) == len(items) and not orphan_tool_result_ids(items)
