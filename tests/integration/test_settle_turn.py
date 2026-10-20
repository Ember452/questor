"""B6 settle_turn：真实 user + 定稿 assistant + 未中断才写回（v3 §6.4b）。"""

from __future__ import annotations

import asyncio

from questor.contracts.events import SubmitMessage
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.kernel.settle import TurnBoundary, TurnSettler
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run

_ANSWER = [StreamChunk(kind="text", text="the codename is ZEPHYR-9"), StreamChunk(kind="finish", finish_reason="stop")]


def _user(text: str) -> Message:
    return Message(id=f"m-{text}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def _seed_only() -> Message:
    return Message(
        id="seed",
        role=Role.USER,
        content=(ContentBlock(type="system_marker", payload={"origin": "seed", "session_id": "s1", "refs": []}),),
        seq=0,
    )


def _loop(store, bus, settler, *, cancel: asyncio.Event | None = None) -> DefaultTurnLoop:  # noqa: ANN001
    return DefaultTurnLoop(
        provider=ScriptedProvider([_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda _name: None,
        store=store,
        workspace_root=None,
        cancel_event=cancel,
        settle=settler.settle,
    )


async def test_settle_writes_real_pair_into_session_scope(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "memory")).connect()
    try:
        bus = InProcessEventBus(store)
        settler = TurnSettler(bus, store, memory, "s1", timeout=5)
        controller = RunController(Run(run_id="run-settle", budget=Budget(max_turns=3)), queue=store, session_id="s1")
        await controller.submit(SubmitMessage(run_id="run-settle", content=_user("remember ZEPHYR-9")), source="cli", idempotency_key="u1")
        final = await _loop(store, bus, settler).drive_controller(controller)
        assert final.status.value == "completed"

        hits = await memory.search("ZEPHYR-9", k=5)
        assert hits and "ZEPHYR-9" in hits[0].snippet
        rows = await store.session_events("s1")
        written = [row for row in rows if row["type"] == "memory_written"]
        assert written and written[0]["run_id"] == "sess:s1" and written[0]["scope"] == "session"
        assert any(row["type"] == "turn_completed" for row in await store.replay("run-settle", 0))
    finally:
        await memory.close()
        await store.close()


async def test_settle_skips_interrupted_boundary(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "memory")).connect()
    try:
        settler = TurnSettler(InProcessEventBus(store), store, memory, "s1", timeout=5)
        wrote = await settler.settle(
            TurnBoundary(run_id="run-x", turn=1, user_text="u", assistant_text="a", interrupted=True, usage={})
        )
        assert wrote is False
        assert all("user:" not in path for path in await memory.list_memory_paths())
    finally:
        await memory.close()
        await store.close()


async def test_settle_skips_system_only_turn(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "memory")).connect()
    try:
        bus = InProcessEventBus(store)
        settler = TurnSettler(bus, store, memory, "s1", timeout=5)
        controller = RunController(Run(run_id="run-system", budget=Budget(max_turns=3)), queue=store, session_id="s1")
        await controller.submit(SubmitMessage(run_id="run-system", content=_seed_only()), source="cli", idempotency_key="seed")
        final = await _loop(store, bus, settler).drive_controller(controller)
        assert final.status.value == "completed"
        assert await store.session_events("s1") == []  # 无真实 user → 不写 session 流
    finally:
        await memory.close()
        await store.close()


async def test_settle_callback_failure_does_not_break_reply(tmp_path) -> None:
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    try:
        async def boom(_boundary: TurnBoundary) -> None:
            raise RuntimeError("memory backend down")

        controller = RunController(Run(run_id="run-boom", budget=Budget(max_turns=3)), queue=store, session_id="s1")
        await controller.submit(SubmitMessage(run_id="run-boom", content=_user("hello")), source="cli", idempotency_key="u1")
        loop = DefaultTurnLoop(
            provider=ScriptedProvider([_ANSWER]),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(store),
            tool_for=lambda _name: None,
            store=store,
            settle=boom,
        )
        final = await loop.drive_controller(controller)
        assert final.status.value == "completed"  # settle 故障不阻塞回复
    finally:
        await store.close()
