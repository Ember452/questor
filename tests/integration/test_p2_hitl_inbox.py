"""P2 HITL：审批必须进入 durable request，并由 Command Inbox 解决。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.events import Cancel, ResolveApproval, SubmitMessage
from questor.contracts.permission import PermissionDecision
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import (
    ApprovalStatus,
    Budget,
    CancelReason,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCallStatus,
)
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permission_policy import PermissionEvaluation, PermissionOutcome
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run


class _AlwaysAsk:
    def evaluate(self, evaluation: PermissionEvaluation) -> PermissionOutcome:
        return PermissionOutcome(
            decision=PermissionDecision.ASK,
            reason="test approval required",
            args_summary=evaluation.tool_name,
        )


class _AskTool(Tool):
    ran = False

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="ask_tool",
            description="tool always requiring approval",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            capability=Capability.WRITE,
            risk=Risk.MEDIUM,
            read_only=False,
        )

    def available(self) -> bool:
        return True

    async def execute(self, args, ctx: ToolContext) -> ToolResult:  # noqa: ANN001
        type(self).ran = True
        return ToolResult(status="success", result="approved")


def _turn() -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc", "name": "ask_tool", "args_delta": "{}"}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


_ANSWER = [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]


def _loop(tmp_path: Path, turns, bus) -> DefaultTurnLoop:
    tool = _AskTool()
    return DefaultTurnLoop(
        provider=ScriptedProvider(turns),
        policy=ReActPolicy(),
        permission=_AlwaysAsk(),
        bus=bus,
        tool_for=lambda name: tool if name == "ask_tool" else None,
        tools=(tool,),
        workspace_root=tmp_path,
    )


def _controller(timeout: float = 0.05) -> RunController:
    return RunController(Run(run_id=new_id("run"), budget=Budget(max_turns=3, approval_timeout_seconds=timeout)))


async def _submit_user(controller: RunController) -> None:
    msg = Message(id="m", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)
    await controller.submit(SubmitMessage(run_id=controller.run.run_id, content=msg), source="test", idempotency_key="submit")


async def test_approval_timeout_expires_and_denies_tool(tmp_path: Path) -> None:
    _AskTool.ran = False
    controller = _controller()
    await _submit_user(controller)
    run = await _loop(tmp_path, [_turn(), _ANSWER], InProcessEventBus(None)).drive_controller(controller)
    call = run.tool_ledger.calls[0]
    assert call.status is ToolCallStatus.DENIED
    assert run.permission_ctx.approvals[0].status is ApprovalStatus.EXPIRED
    assert run.status is RunStatus.COMPLETED
    assert _AskTool.ran is False


async def test_external_resolve_allow_executes_tool(tmp_path: Path) -> None:
    """HTTP/SSE-style approver attaches after emit and still replays the durable approval_request."""
    _AskTool.ran = False
    controller = _controller(timeout=2)
    await _submit_user(controller)
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    loop = _loop(tmp_path, [_turn(), _ANSWER], bus)

    async def approve() -> None:
        async for event in bus.subscribe(controller.run.run_id, 0):
            if event.type == "approval_request":
                await controller.submit(
                    ResolveApproval(
                        run_id=controller.run.run_id,
                        request_id=event.data["request_id"],
                        decision="allow",
                        decided_by="http_client",
                    ),
                    source="http",
                    idempotency_key=event.data["request_id"],
                )
                return

    task = asyncio.create_task(approve())
    run = await loop.drive_controller(controller)
    await task
    assert run.status is RunStatus.COMPLETED
    assert run.tool_ledger.calls[0].status is ToolCallStatus.SUCCESS
    assert run.permission_ctx.approvals[0].decided_by == "http_client"
    assert _AskTool.ran is True
    await store.close()


async def test_cancel_while_awaiting_approval_closes_request(tmp_path: Path) -> None:
    _AskTool.ran = False
    controller = _controller(timeout=2)
    await _submit_user(controller)
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    loop = _loop(tmp_path, [_turn(), _ANSWER], bus)

    async def cancel_after_request() -> None:
        async for event in bus.subscribe(controller.run.run_id, 0):
            if event.type == "approval_request":
                await controller.submit(
                    Cancel(run_id=controller.run.run_id, reason=CancelReason.USER),
                    source="test",
                    idempotency_key="cancel",
                )
                return

    task = asyncio.create_task(cancel_after_request())
    run = await loop.drive_controller(controller)
    await task
    assert run.status is RunStatus.CANCELLED
    assert run.permission_ctx.approvals[0].status is ApprovalStatus.CANCELLED
    assert run.tool_ledger.calls[0].status is ToolCallStatus.CANCELLED
    assert _AskTool.ran is False
    await store.close()
