"""P1 T13 DoD — end-to-end turn loop (ROADMAP §2.5 items 1 & 2), no network.

Drives ``DefaultTurnLoop`` with a scripted provider to prove:
- happy path: SubmitMessage -> turn -> ProposeAction(read) -> tool_completed -> run_completed;
- exception paths that must NOT crash: user cancel, tool denied (sensitive path),
  and an illegal intent (unknown tool).
Exactly one terminal event per run (C13); the ledger stays paired (C7).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, RunStatus, ToolCallStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run


def _read_tool() -> ReadTool:
    return ReadTool()


def _tool_for(reg: dict) -> object:
    return lambda name: reg.get(name)


def _make_loop(tmp: Path, turns, *, permission=None, cancel=None):
    read = _read_tool()
    reg = {"read": read}
    store = None
    return DefaultTurnLoop(
        provider=ScriptedProvider(turns),
        policy=ReActPolicy(),
        permission=permission or DefaultPermissionEngine(read_only_tools=frozenset({"read"})),
        bus=InProcessEventBus(store),
        tool_for=_tool_for(reg),
        tools=(read,),
        workspace_root=tmp,
        model="test-model",
        cancel_event=cancel,
    ), store


def _run() -> Run:
    return Run(run_id="run_test", budget=Budget(max_turns=5))


_TURN_TOOLCALL = [
    StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc_1", "name": "read", "args_delta": '{"file_path": "a.txt"}'}),
    StreamChunk(kind="finish", finish_reason="tool_calls"),
]
_TURN_ANSWER = [StreamChunk(kind="text", text="all done"), StreamChunk(kind="finish", finish_reason="stop")]


async def test_happy_path_run_completed(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("contents", encoding="utf-8")
    loop, _ = _make_loop(tmp_path, [_TURN_TOOLCALL, _TURN_ANSWER])
    run = await loop.drive(_run(), "read a.txt")
    assert run.status is RunStatus.COMPLETED
    assert run.tool_ledger.calls[0].status is ToolCallStatus.SUCCESS
    terminals = [i for i in run.context.items]  # sanity: history grew
    assert terminals


async def test_exactly_one_terminal_event(tmp_path: Path) -> None:
    store = await SQLiteStore(":memory:").connect()
    read = _read_tool()
    bus = InProcessEventBus(store)
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([_TURN_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(read_only_tools=frozenset({"read"})),
        bus=bus,
        tool_for=lambda n: {"read": read}.get(n),
        tools=(read,),
        workspace_root=tmp_path,
    )
    await loop.drive(_run(), "hi")
    events = await store.replay("run_test", 0)
    terminal = [e for e in events if e["type"] in {"run_completed", "run_cancelled", "run_failed"}]
    assert len(terminal) == 1
    assert await store.sequence_head("run_test") == max(e["seq"] for e in events)
    await store.close()


async def test_user_cancel_backfills_open_tool(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    cancel = asyncio.Event()
    cancel.set()  # cancel observed at the first safe point
    loop, _ = _make_loop(tmp_path, [_TURN_TOOLCALL, _TURN_ANSWER], cancel=cancel)
    run = await loop.drive(_run(), "read a.txt")
    assert run.status is RunStatus.CANCELLED
    # no open tool_call left dangling after cancel (C7)
    from questor.contracts.state_schema import OPEN_TOOL_CALL_STATUSES

    assert all(c.status not in OPEN_TOOL_CALL_STATUSES for c in run.tool_ledger.calls)


async def test_sensitive_tool_denied_does_not_crash(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("SECRET=1", encoding="utf-8")
    turn_secret = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc_d", "name": "read", "args_delta": '{"file_path": ".env"}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    loop, _ = _make_loop(tmp_path, [turn_secret, _TURN_ANSWER])
    run = await loop.drive(_run(), "read .env")
    denied = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc_d")
    assert denied.status is ToolCallStatus.DENIED
    assert run.status is RunStatus.COMPLETED  # loop kept going after the deny


async def test_illegal_unknown_tool_rejected_not_crash(tmp_path: Path) -> None:
    bad = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc_u", "name": "does_not_exist", "args_delta": "{}"}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    loop, _ = _make_loop(tmp_path, [bad, _TURN_ANSWER])
    run = await loop.drive(_run(), "call unknown")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc_u")
    assert call.status is ToolCallStatus.ERROR  # recorded as error, pairing kept
    assert run.status is RunStatus.COMPLETED
