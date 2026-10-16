"""RunController 接入 turn loop 的安全点消费语义（ADR-0013）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id
from questor.contracts.events import Cancel, SubmitMessage
from questor.contracts.inbox import InboxStatus
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.state.domain_state import Run

_ANSWER = [StreamChunk(kind="text", text="ok"), StreamChunk(kind="finish", finish_reason="stop")]


def _loop(tmp_path: Path) -> DefaultTurnLoop:
    read = ReadTool()
    return DefaultTurnLoop(
        provider=ScriptedProvider([_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        workspace_root=tmp_path,
    )


def _run() -> Run:
    return Run(run_id=new_id("run"), budget=Budget(max_turns=3))


def _user_message(text: str) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


async def test_controller_prequeued_cancel_terminates_before_provider(tmp_path: Path) -> None:
    controller = RunController(_run())
    await controller.submit(Cancel(run_id=controller.run.run_id, reason=CancelReason.USER), source="test", idempotency_key="cancel")
    run = await _loop(tmp_path).drive_controller(controller)
    assert run.status is RunStatus.CANCELLED
    assert controller.closed is True


async def test_controller_prequeued_submit_runs_to_completion(tmp_path: Path) -> None:
    run = _run()
    controller = RunController(run)
    msg = _user_message("hi")
    await controller.submit(SubmitMessage(run_id=run.run_id, content=msg), source="test", idempotency_key="submit")
    final = await _loop(tmp_path).drive_controller(controller)
    assert final.status is RunStatus.COMPLETED
    assert msg.id in {m.id for m in final.context.items}
    assert controller.closed is True


async def test_terminal_controller_rejects_late_command(tmp_path: Path) -> None:
    run = _run()
    controller = RunController(run)
    msg = _user_message("hi")
    await controller.submit(SubmitMessage(run_id=run.run_id, content=msg), source="test", idempotency_key="submit")
    await _loop(tmp_path).drive_controller(controller)
    receipt = await controller.submit(
        Cancel(run_id=run.run_id, reason=CancelReason.USER),
        source="late",
        idempotency_key="late",
    )
    assert receipt.status is InboxStatus.REJECTED_TERMINAL
