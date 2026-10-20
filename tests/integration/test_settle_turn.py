"""B6 settle_turn：真实 user + 定稿 assistant + 未中断才写回（v3 §6.4b）。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from questor.contracts.events import SubmitMessage
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.kernel.settle import TurnBoundary, TurnSettler
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Context, Run
from questor.state.snapshot import to_snapshot
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

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


async def _stores(tmp_path):  # noqa: ANN202
    store = await SQLiteStore(str(tmp_path / "state.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "memory")).connect()
    return store, memory


def _surface(tmp_path, store, memory) -> CliSurface:  # noqa: ANN001
    return CliSurface(workspace_root=tmp_path, store=store, memory_store=memory, provider=ScriptedProvider([_ANSWER]))


def _checkpoint_blob(run: Run) -> dict:
    return {
        "cp_id": f"cp-{run.run_id}",
        "run_id": run.run_id,
        "seq": 0,
        "turn": 0,
        "kind": "auto",
        "state_digest": json.dumps(to_snapshot(run)),
        "pending": [],
    }


async def _memory_scoped_rows(store: SQLiteStore, session_id: str) -> list[dict]:
    return [row for row in await store.session_events(session_id) if row["type"] == "memory_written" and row["scope"] == "session"]


async def test_cli_run_once_settles_into_session_scope(tmp_path) -> None:
    store, memory = await _stores(tmp_path)
    try:
        final = await _surface(tmp_path, store, memory).run_once("remember ZEPHYR-9")
        sid = await store.run_session(final.run_id)
        assert sid is not None
        hits = await memory.search("ZEPHYR-9", k=5)
        assert hits and "ZEPHYR-9" in hits[0].snippet
        rows = await _memory_scoped_rows(store, sid)
        assert rows and rows[0]["run_id"] == f"sess:{sid}"
    finally:
        await memory.close()
        await store.close()


async def test_cli_resume_settles_into_session_scope(tmp_path) -> None:
    store, memory = await _stores(tmp_path)
    try:
        sid = await store.create_session("s-resume")
        await store.bind_run_session("run-resume", sid)
        run = Run(
            run_id="run-resume",
            status=RunStatus.RUNNING,
            budget=Budget(max_turns=3),
            context=Context(items=(_user("remember RESUMEX"),)),
        )
        await store.save_checkpoint(_checkpoint_blob(run))
        final = await _surface(tmp_path, store, memory).resume("run-resume")
        assert final is not None and final.status is RunStatus.COMPLETED
        hits = await memory.search("ZEPHYR-9", k=5)
        assert hits and "ZEPHYR-9" in hits[0].snippet
        assert await _memory_scoped_rows(store, sid)
    finally:
        await memory.close()
        await store.close()


async def _wait_task(server: EventServer, run_id: str) -> None:
    active = server.registry._runs.get(run_id)  # noqa: SLF001 - 测试观察点
    assert active is not None and active.task is not None
    await active.task


async def test_http_start_and_resume_settle_into_session_scope(tmp_path) -> None:
    store, memory = await _stores(tmp_path)
    try:
        server = EventServer(_surface(tmp_path, store, memory), store)
        run_id = await server.start_run("remember HTTPZ", session_id="s-http")
        await _wait_task(server, run_id)
        assert (await memory.search("ZEPHYR-9", k=5))[0].snippet
        assert await _memory_scoped_rows(store, "s-http")

        await store.bind_run_session("run-http-resume", "s-http")
        run = Run(
            run_id="run-http-resume",
            status=RunStatus.RUNNING,
            budget=Budget(max_turns=3),
            context=Context(items=(_user("remember RESUMEX"),)),
        )
        await store.save_checkpoint(_checkpoint_blob(run))
        resumed = await server.resume("run-http-resume")
        await _wait_task(server, resumed)
        hits = await memory.search("ZEPHYR-9", k=5)
        assert hits and "ZEPHYR-9" in hits[0].snippet
    finally:
        await memory.close()
        await store.close()


async def test_openai_lane_settles_into_session_scope(tmp_path) -> None:
    store, memory = await _stores(tmp_path)
    try:
        server = EventServer(_surface(tmp_path, store, memory), store)
        app = create_app(server, openai_api_keys=["sk-test"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://svc", trust_env=False, timeout=30) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer sk-test"},
                json={"messages": [{"role": "user", "content": "remember OPENAIZ"}]},
            )
            assert response.status_code == 200
        hits = await memory.search("ZEPHYR-9", k=5)
        assert hits and "ZEPHYR-9" in hits[0].snippet
    finally:
        await memory.close()
        await store.close()


def _wait_bootstrap(path: Path, deadline: float) -> dict:
    while time.monotonic() < deadline:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("port"):
                    return data
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    raise AssertionError("sidecar never wrote bootstrap")


@pytest.mark.timeout(180)
def test_sidecar_entry_settles_into_memory(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    bootstrap = tmp_path / "sidecar.json"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(root),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "QUESTOR_SIDECAR_BOOTSTRAP": str(bootstrap),
        "QUESTOR_SIDECAR_GENERATION": "3",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    env.pop("QUESTOR_MODEL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "questor", "--serve"],
        env=env,
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        try:
            boot = _wait_bootstrap(bootstrap, deadline=time.monotonic() + 40)
        except AssertionError:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.skip(f"real uvicorn sidecar unavailable (UNVERIFIED): {out[-400:]}")
        base = f"http://127.0.0.1:{boot['port']}"
        headers = {"x-questor-token": boot["token"]}
        with httpx.Client(base_url=base, timeout=None, trust_env=False, headers=headers) as client:
            run_id = client.post("/run", json={"text": "remember SIDECAR-7"}).json()["run_id"]
            client.get(f"/events/{run_id}")  # 跟到终态
        proc.terminate()
        proc.wait(timeout=10)
        texts = "".join(path.read_text(encoding="utf-8") for path in root.glob("**/*.md"))
        assert "SIDECAR-7" in texts
    finally:
        if proc.poll() is None:
            proc.kill()
