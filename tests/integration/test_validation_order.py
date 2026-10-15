"""T4：五层校验次序与非法 JSON 的 fail-closed 语义。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id
from questor.contracts.events import MarkToolValidated, SubmitMessage
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import (
    Budget,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolArgsStatus,
    ToolCall,
    ToolCallStatus,
)
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import PermissionDecision
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.state.domain_state import Run, ToolLedger
from questor.state.reduce import reduce


class _SpyPermission:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, tool_name: str, arguments=None) -> tuple[str, str]:  # noqa: ANN001
        self.calls += 1
        return PermissionDecision.ALLOW.value, "test allow"


class _RecordingRead(ReadTool):
    executed = False

    async def execute(self, args, ctx):  # noqa: ANN001
        type(self).executed = True
        return await super().execute(args, ctx)


def _loop(tmp_path: Path, turns, permission):  # noqa: ANN001
    _RecordingRead.executed = False
    read = _RecordingRead()
    return DefaultTurnLoop(
        provider=ScriptedProvider(turns),
        policy=ReActPolicy(),
        permission=permission,
        bus=InProcessEventBus(None),
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        workspace_root=tmp_path,
    )


async def test_malformed_tool_args_keeps_raw_and_does_not_reach_permission(tmp_path: Path) -> None:
    turn = [
        StreamChunk(
            kind="tool_call",
            tool_call={"index": 0, "id": "tc_bad", "name": "read", "args_delta": '{"file_path":'},
        ),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    permission = _SpyPermission()
    loop = _loop(tmp_path, [turn, [StreamChunk(kind="finish", finish_reason="stop")]], permission)
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=3)), "bad args")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc_bad")
    assert call.status is ToolCallStatus.ERROR
    assert call.args_status is ToolArgsStatus.INVALID
    assert call.raw_args_summary == '{"file_path":'
    assert "invalid json" in str(call.result).lower()
    assert permission.calls == 0
    assert _RecordingRead.executed is False
    assert run.status is RunStatus.COMPLETED


async def test_schema_validation_happens_before_permission(tmp_path: Path) -> None:
    turn = [
        StreamChunk(
            kind="tool_call",
            tool_call={"index": 0, "id": "tc_schema", "name": "read", "args_delta": '{"unexpected": true}'},
        ),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    permission = _SpyPermission()
    loop = _loop(tmp_path, [turn, [StreamChunk(kind="finish", finish_reason="stop")]], permission)
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=3)), "bad schema")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc_schema")
    assert call.status is ToolCallStatus.ERROR
    assert "invalid arguments" in str(call.result)
    assert permission.calls == 0
    assert _RecordingRead.executed is False


def test_mark_tool_validated_only_pending_transitions_and_is_idempotent() -> None:
    pending = ToolCall(tool_call_id="tc", turn=1, name="read", args={})
    run_with_pending = Run(run_id="r", budget=Budget(), tool_ledger=ToolLedger((pending,)))
    validated_run, validated_events = reduce(run_with_pending, MarkToolValidated(run_id="r", tool_call_id="tc"))
    assert validated_run.tool_ledger.calls[0].status is ToolCallStatus.VALIDATED
    assert validated_events == []
    replay_run, replay_events = reduce(validated_run, MarkToolValidated(run_id="r", tool_call_id="tc"))
    assert replay_run.tool_ledger.calls[0].status is ToolCallStatus.VALIDATED
    assert replay_events == []


async def test_schema_valid_tool_transitions_through_validated_before_result(tmp_path: Path) -> None:
    _RecordingRead.executed = False
    read = _RecordingRead()
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    turn = [
        StreamChunk(
            kind="tool_call",
            tool_call={"index": 0, "id": "tc_ok", "name": "read", "args_delta": '{"file_path": "a.txt"}'},
        ),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]

    class _ObservingPermission(_SpyPermission):
        def __init__(self, controller) -> None:
            super().__init__()
            self.controller = controller

        def evaluate(self, tool_name, arguments=None):  # noqa: ANN001
            call = next(c for c in self.controller.run.tool_ledger.calls if c.tool_call_id == "tc_ok")
            assert call.status is ToolCallStatus.VALIDATED
            return super().evaluate(tool_name, arguments)

    controller = RunController(Run(run_id="run-test", budget=Budget(max_turns=3)))
    permission = _ObservingPermission(controller)
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([turn, [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]]),
        policy=ReActPolicy(),
        permission=permission,
        bus=InProcessEventBus(None),
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        workspace_root=tmp_path,
    )
    msg = Message(id="m", role=Role.USER, content=(ContentBlock(type="text", text="read"),), seq=0)
    await controller.submit(SubmitMessage(run_id="run-test", content=msg), source="test", idempotency_key="submit")
    run = await loop.drive_controller(controller)
    assert permission.calls == 1
    assert run.tool_ledger.calls[0].status is ToolCallStatus.SUCCESS
    assert _RecordingRead.executed is True
