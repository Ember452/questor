"""T14：loop 使用冻结 RunToolSurface（工具面 + 误名候选来自 registry）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import ToolRegistry
from questor.contracts.common import new_id
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ToolCallStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.state.domain_state import Run


async def test_loop_uses_frozen_surface_and_candidate_hint(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(ReadTool())
    surface = registry.freeze_for_run("r")
    turn = [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc1", "name": "redi", "args_delta": '{"file_path": "a.txt"}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]
    answer = [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([turn, answer]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=surface.tool_for,
        tools=surface.tools,
        surface=surface,
        workspace_root=tmp_path,
    )
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=3)), "call redi")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.ERROR
    assert "did you mean" in str(call.result)
    assert "read" in str(call.result)
