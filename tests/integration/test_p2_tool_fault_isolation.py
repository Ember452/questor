"""P2 审计修复 #1/#7：工具故障与超时都由 Harness 兜底，绝不击穿单写者循环（C8/C10）。

design/03 §8 承诺"每个工具由 Harness 武装 deadline、panic 转结构化 error"。若工具异常直接上抛，
run 会崩、tool_call 悬在 RUNNING、配对不变式（I1）被破坏——这两条测试就是钉这个的。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ToolCallStatus
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.state.domain_state import Run


class _BoomTool(Tool):
    spec = ToolSpec(
        name="boom",
        description="read-only tool that always raises, to prove the harness shields tool panics",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        capability=Capability.READONLY,
        risk=Risk.LOW,
        read_only=True,
    )

    def available(self) -> bool:
        return True

    async def execute(self, args: object, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("kaboom")


class _SlowTool(Tool):
    spec = ToolSpec(
        name="slow",
        description="read-only tool that outlives its own deadline, to prove the harness arms timeouts",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        capability=Capability.READONLY,
        risk=Risk.LOW,
        read_only=True,
        timeout_s=0.05,
    )

    def available(self) -> bool:
        return True

    async def execute(self, args: object, ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(30)
        return ToolResult(status="success", result="should never get here")


def _propose(name: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": f"tc-{name}", "name": name, "args_delta": "{}"}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


_ANSWER = [StreamChunk(kind="text", text="recovered"), StreamChunk(kind="finish", finish_reason="stop")]


def _loop(tmp_path: Path, bus: InProcessEventBus, tools: tuple[Tool, ...]) -> DefaultTurnLoop:
    by_name = {tool.spec.name: tool for tool in tools}
    return DefaultTurnLoop(
        provider=ScriptedProvider([_propose(tools[0].spec.name), _ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=by_name.get,
        tools=tools,
        workspace_root=tmp_path,
    )


async def test_tool_panic_becomes_error_result_and_run_survives(tmp_path: Path) -> None:
    bus = InProcessEventBus(None)
    loop = _loop(tmp_path, bus, (_BoomTool(),))
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=3)), "go")

    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc-boom")
    assert call.status is ToolCallStatus.ERROR
    assert "RuntimeError" in str(call.result)
    # 配对不变式：panic 之后仍必须有对应 tool_result 回填给模型。
    assert any(b.type == "tool_result" and b.tool_use_id == "tc-boom" for m in run.context.items for b in m.content)
    assert run.status.value == "completed"  # run 不崩，继续跑到终态


async def test_tool_deadline_is_armed_by_harness_not_by_tool(tmp_path: Path) -> None:
    """文件/read 类工具不经过 ProcessRunner，但同样必须受 Harness 的 deadline 约束。"""
    bus = InProcessEventBus(None)
    loop = _loop(tmp_path, bus, (_SlowTool(),))
    run = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=3)), "go")

    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc-slow")
    assert call.status is ToolCallStatus.TIMED_OUT, call.status
    assert "deadline" in str(call.result).lower() or "timeout" in str(call.result).lower()
    assert run.status.value == "completed"
