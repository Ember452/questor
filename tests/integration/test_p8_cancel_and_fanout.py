"""P8 T8/T13：取消传播 + fan-out gate 判据（ADR-0038/0041）。

- 父终态 → ``on_parent_terminal`` 向每个 live 子提 ``Cancel(owner)``，子经 reduce 落 cancelled（不硬杀）。
- fan-out gate：深度超限 / 宽度超限在 **建子之前** 拒（返回 reason、不产生孤儿子、不崩）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.state_schema import Budget, CancelReason, RunStatus
from questor.contracts.subagent import SpawnRequest
from questor.kernel.events import InProcessEventBus
from questor.kernel.run_control import RunController
from questor.providers.fake import EchoProvider
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.run_registry import RunRegistry
from questor.surfaces.subagent_orchestrator import SubagentOrchestrator


def _harness(tmp_path: Path) -> tuple[CliSurface, InProcessEventBus, RunRegistry, SubagentOrchestrator]:
    surface = CliSurface(workspace_root=tmp_path, provider=EchoProvider(), model="test")
    bus = InProcessEventBus(store=None)
    registry = RunRegistry()
    orchestrator = SubagentOrchestrator(surface=surface, store=None, bus=bus, registry=registry)
    return surface, bus, registry, orchestrator


async def test_parent_terminal_cancels_live_child(tmp_path: Path) -> None:
    surface, bus, registry, orchestrator = _harness(tmp_path)
    registry.register(RunController(Run(run_id="parent")))
    child_controller = RunController(Run(run_id="child", budget=Budget()))
    registry.register(child_controller)
    orchestrator._children["parent"] = {"child"}  # 模拟 delegate 已登记的 live 子

    await orchestrator.on_parent_terminal("parent")  # 父 terminal → 提 Cancel(owner) 进子 inbox

    tool_surface = surface._freeze_surface("child", [])
    loop = surface._loop(bus, asyncio.Event(), tool_surface, subagent_spawner=orchestrator)
    result = await asyncio.wait_for(loop.drive_controller(child_controller), timeout=10)
    # 子经 reduce Cancel 收敛：cancelled + owner 归因（非 out-of-band 硬杀）。
    assert result.status is RunStatus.CANCELLED
    assert result.cancel_reason is CancelReason.OWNER


async def test_depth_exceeded_refused_before_spawn(tmp_path: Path) -> None:
    _, _, registry, orchestrator = _harness(tmp_path)
    registry.register(RunController(Run(run_id="parent", budget=Budget(max_tree_depth=1))))
    orchestrator._depth["parent"] = 1  # 父本身已是子（深度 1）→ 再生孙 = 2 > 1
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n", objective="SUBTASK::nest"))
    assert not result.accepted and result.reason == "depth_exceeded"
    assert registry.get(result.child_run_id) is None if result.child_run_id else True  # 未建孤儿子


async def test_width_exceeded_refused_before_spawn(tmp_path: Path) -> None:
    _, _, registry, orchestrator = _harness(tmp_path)
    registry.register(RunController(Run(run_id="parent", budget=Budget(max_parallel_children=1))))
    orchestrator._children["parent"] = {"existing-child"}  # 已占满宽度
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n", objective="SUBTASK::more"))
    assert not result.accepted and result.reason == "fanout_exceeded"


async def test_unknown_parent_refused(tmp_path: Path) -> None:
    _, _, _, orchestrator = _harness(tmp_path)
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="ghost", node_id="n", objective="SUBTASK::x"))
    assert not result.accepted and result.reason == "unknown_parent"
