"""P8 DoD①②：两个真 run 协作完成一任务（同进程 asyncio），父经事件流拿子终态、无旁路写。

脚本化 provider 路由：父 turn1 调 `delegate` → orchestrator 起独立子 run（自己的账本）→ 子终态经
ReportChildTerminal 回父 → 父 durable 流出现 peer_started + peer_ended；子有自己 run_started/run_completed。
全用 bus observer 收**投影后**事件（承 ADR-0033 bus 级唯一投影），不起真 store/HTTP/LLM。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from questor.contracts.events import SubmitMessage
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import (
    Budget,
    ContentBlock,
    Message,
    PermissionRule,
    Role,
    RunStatus,
    TaskKind,
    TaskStatus,
)
from questor.kernel.events import Envelope, InProcessEventBus
from questor.kernel.run_control import RunController
from questor.state.domain_state import PermissionCtx, Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.run_registry import RunRegistry
from questor.surfaces.subagent_orchestrator import SubagentOrchestrator

_CHILD_MARKER = "SUBTASK::"


class _RoutingProvider(ProviderPort):
    """父无 tool_result 时→调 delegate；父有 tool_result 或子→给终文本。"""

    def __init__(self) -> None:
        self.served: list[str] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        msgs = request.messages
        users = [m for m in msgs if m.role is Role.USER]
        last_user_text = "".join(b.text or "" for b in (users[-1].content if users else ())) if users else ""
        has_tool_result = any(b.type == "tool_result" for m in msgs for b in m.content)
        is_child = len(msgs) == 1 and last_user_text.startswith(_CHILD_MARKER)
        if is_child:
            self.served.append("child")
            yield StreamChunk(kind="text", text="child-answer")
            yield StreamChunk(kind="finish", finish_reason="stop")
        elif has_tool_result:
            self.served.append("parent-final")
            yield StreamChunk(kind="text", text="all done")
            yield StreamChunk(kind="finish", finish_reason="stop")
        else:
            self.served.append("parent-delegate")
            yield StreamChunk(
                kind="tool_call",
                tool_call={"index": 0, "id": "dlg1", "name": "delegate", "args_delta": '{"objective": "SUBTASK::summarize"}'},
            )
            yield StreamChunk(kind="finish", finish_reason="tool_calls")


async def test_two_runs_collaborate_parent_observes_child_terminal(tmp_path: Path) -> None:
    provider = _RoutingProvider()
    surface = CliSurface(workspace_root=tmp_path, provider=provider, model="test-model")
    bus = InProcessEventBus(store=None)
    registry = RunRegistry()
    orchestrator = SubagentOrchestrator(surface=surface, store=None, bus=bus, registry=registry)

    seen: list[Envelope] = []
    bus.add_observer(seen.append)  # bus 级只读 observer（ADR-0033）：收投影后事件

    parent = Run(
        run_id="parent",
        budget=Budget(max_turns=5),
        permission_ctx=PermissionCtx(
            mode="default",
            rules=(PermissionRule(id="allow-delegate", tool_pattern="delegate", argument_pattern="*", action="allow"),),
        ),
    )
    controller = RunController(parent)
    registry.register(controller)
    msg = Message(id="m0", role=Role.USER, content=(ContentBlock(type="text", text="summarize the repo"),), seq=0)
    await registry.submit("parent", SubmitMessage(run_id="parent", content=msg), source="test", idempotency_key="submit:parent")

    tool_surface = surface._freeze_surface("parent", [])
    loop = surface._loop(bus, asyncio.Event(), tool_surface, subagent_spawner=orchestrator)
    result = await asyncio.wait_for(loop.drive_controller(controller), timeout=20)

    assert result.status is RunStatus.COMPLETED
    parent_events = [e.type for e in seen if e.run_id == "parent"]
    # 父事件流：spawn→终态回报，且无旁路写（peer_* 都是父 reduce 产的父事件）。
    assert "peer_started" in parent_events and "peer_ended" in parent_events

    started = next(e for e in seen if e.type == "peer_started")
    child_run_id = started.data["child_run_id"]
    assert child_run_id and child_run_id != "parent"  # 独立 run
    # 子在自己的账本里 run_started→run_completed（父不写子状态）。
    child_events = [e.type for e in seen if e.run_id == child_run_id]
    assert "run_started" in child_events and "run_completed" in child_events
    # 父 task_tree 节点被绑定且回填终态（经 ReportChildTerminal 回灌，非直写）。
    node = next(n for n in result.task_tree.nodes if n.kind is TaskKind.SUBAGENT)
    assert node.assigned_run_id == child_run_id and node.status is TaskStatus.DONE
    # W5-017：子完成后编排表必须回收（不留 _child_tasks/_depth/空父集）。
    await asyncio.sleep(0)
    assert orchestrator._child_tasks == {}, f"子任务表未回收：{orchestrator._child_tasks}"
    assert orchestrator._depth == {}, f"深度表未回收：{orchestrator._depth}"
    assert orchestrator._children == {}, f"父孩子集未剪空：{orchestrator._children}"
