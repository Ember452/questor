"""P1 加固 DoD —— 审计修复：C10 策略隔离、A2 护栏、A1 恢复。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id
from questor.contracts.errors import ErrorKind
from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, RunStatus, ToolCallStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import resume_run
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run


class _PanickingPolicy(PolicyPort):
    id = "panic"
    fingerprint = "panic:1"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        raise RuntimeError("boom")


def _tool_turn(call_id: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "read", "args_delta": '{"file_path": "a.txt"}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


_ANSWER = [StreamChunk(kind="text", text="done"), StreamChunk(kind="usage", usage={"total_tokens": 5000}), StreamChunk(kind="finish", finish_reason="stop")]


def _loop(provider, *, policy=None, budget=None, store=None, tmp=None):
    read = ReadTool()
    return DefaultTurnLoop(
        provider=provider,
        policy=policy or ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(store),
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        store=store,
        workspace_root=tmp or Path("."),
        model="m",
    )


async def test_run_survives_panicking_policy_and_fails_gracefully(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    loop = _loop(ScriptedProvider([[_ANSWER[0], _ANSWER[2]]]), policy=_PanickingPolicy(), tmp=tmp_path)
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=20)), "hi")
    # never raised; isolated after repeated faults -> graceful failure
    assert run.status is RunStatus.FAILED
    assert run.error_stack[-1].kind is ErrorKind.POLICY_VIOLATION


async def test_repeat_tool_call_triggers_no_progress_guard(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider([_tool_turn(f"tc_{i}") for i in range(12)])
    loop = _loop(provider, budget=Budget(max_turns=50, repeat_tool_limit=3), tmp=tmp_path)
    run = await loop.drive(Run(run_id="run_repeat", budget=Budget(max_turns=50, repeat_tool_limit=3)), "read")
    assert run.status is RunStatus.FAILED
    assert "repeated" in run.error_stack[-1].message.lower()


async def test_max_tokens_budget_terminates(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider([_tool_turn("tc_1"), _ANSWER])
    loop = _loop(provider, tmp=tmp_path)
    run = await loop.drive(Run(run_id="run_tok", budget=Budget(max_turns=5, max_tokens=100)), "read then answer")
    # usage from the answer turn pushes past the 100-token budget
    assert run.status is RunStatus.FAILED
    assert "token budget" in run.error_stack[-1].message.lower()


async def test_checkpoint_and_resume_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("payload", encoding="utf-8")
    db = str(tmp_path / "db.sqlite")
    store = await SQLiteStore(db).connect()
    loop = _loop(ScriptedProvider([_tool_turn("tc_1"), _ANSWER]), store=store, tmp=tmp_path)
    final = await loop.drive(Run(run_id="run_res", budget=Budget(max_turns=5)), "read a.txt")
    await store.close()

    # reopen (simulates a fresh process) and resume from the last checkpoint
    store2 = await SQLiteStore(db).connect()
    resumed = await resume_run(store2, "run_res")
    await store2.close()

    assert resumed is not None
    assert resumed.run_id == final.run_id
    assert resumed.seq > 0
    read_calls = [c for c in resumed.tool_ledger.calls if c.name == "read"]
    assert read_calls and read_calls[0].status is ToolCallStatus.SUCCESS
