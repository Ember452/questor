"""P8 T8/T13/F7：取消传播 + fan-out gate 判据（ADR-0038/0040/0041）。

覆盖审计 F7 三类缺口——全部走**真路径**（非手改内部字典）：
- 深度/未知父：在建子前拒（白盒 gate）。
- **宽度门真可达**：fire-and-forget（`wait=False`）真起一个 live 子，第二次并发 spawn 撞 `max_parallel_children`。
- **真 delegate 起子 + 父终态冻结子树**：子经真子 run 落到 write `ask` 安全点，`on_parent_terminal` 提
  `Cancel(owner)` → 子收敛 cancelled 且**回填 open tool_use 无悬空**（C7）；并端到端证 **父 full_auto 不传染子**（DoD④，ADR-0040）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from questor.contracts.ports import ProviderRequest, StreamChunk
from questor.contracts.state_schema import Budget, CancelReason, RunStatus
from questor.contracts.subagent import SpawnRequest
from questor.kernel.events import InProcessEventBus
from questor.kernel.run_control import RunController
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import PermissionCtx, Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.run_registry import RunRegistry
from questor.surfaces.subagent_orchestrator import SubagentOrchestrator


class _BlockingProvider:
    """子 provider 阻塞在 release 上：保持子 live，直到测试放行。"""

    def __init__(self, release: asyncio.Event) -> None:
        self._release = release

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        await self._release.wait()
        yield StreamChunk(kind="text", text="done")
        yield StreamChunk(kind="finish", finish_reason="stop")


class _WriteAskProvider:
    """子 provider turn1 发一个 `write` 工具调用 → 子（default mode）落 ask、卡在安全点。"""

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            kind="tool_call",
            tool_call={"index": 0, "id": "w1", "name": "write", "args_delta": '{"file_path": "out.txt", "content": "x"}'},
        )
        yield StreamChunk(kind="finish", finish_reason="tool_calls")


def _harness(tmp_path: Path, provider: object) -> tuple[CliSurface, RunRegistry, SubagentOrchestrator]:
    surface = CliSurface(workspace_root=tmp_path, provider=provider, model="test")  # type: ignore[arg-type]
    bus = InProcessEventBus(store=None)
    registry = RunRegistry()
    orchestrator = SubagentOrchestrator(surface=surface, store=None, bus=bus, registry=registry)
    return surface, registry, orchestrator


async def test_depth_exceeded_refused_before_spawn(tmp_path: Path) -> None:
    _, registry, orchestrator = _harness(tmp_path, _BlockingProvider(asyncio.Event()))
    registry.register(RunController(Run(run_id="parent", budget=Budget(max_tree_depth=1))))
    orchestrator._depth["parent"] = 1  # 父已是子 → 生孙 = 2 > 1
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n", objective="SUBTASK::nest"))
    assert not result.accepted and result.reason == "depth_exceeded"
    assert result.child_run_id is None  # 被拒即无 child_run_id、绝不建孤儿子


async def test_unknown_parent_refused(tmp_path: Path) -> None:
    _, _, orchestrator = _harness(tmp_path, _BlockingProvider(asyncio.Event()))
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="ghost", node_id="n", objective="SUBTASK::x"))
    assert not result.accepted and result.reason == "unknown_parent"


async def test_width_gate_reachable_via_real_fire_and_forget(tmp_path: Path) -> None:
    """fire-and-forget 真起 live 子 → 第二个并发 spawn 撞宽度门（真路径，非手改 _children）。"""
    release = asyncio.Event()
    _, registry, orchestrator = _harness(tmp_path, _BlockingProvider(release))
    registry.register(RunController(Run(run_id="parent", budget=Budget(max_parallel_children=1))))
    first = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n1", objective="SUBTASK::a", wait=False))
    assert first.accepted and first.child_run_id
    child_task = orchestrator._child_tasks[first.child_run_id]
    second = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n2", objective="SUBTASK::b", wait=False))
    assert not second.accepted and second.reason == "fanout_exceeded"  # child1 仍 live → 宽度门真触发
    release.set()
    await asyncio.wait_for(child_task, timeout=10)  # 子1放行后跑完、清理


async def test_parent_terminal_cancels_live_child_no_dangling(tmp_path: Path) -> None:
    """真 delegate 起子→子落 write ask→父 on_parent_terminal→子 cancelled + 回填无悬空 tool_use。"""
    surface, registry, orchestrator = _harness(tmp_path, _WriteAskProvider())
    registry.register(
        RunController(Run(run_id="parent", budget=Budget(), permission_ctx=PermissionCtx(mode="full_auto")))
    )
    result = await orchestrator.delegate(SpawnRequest(parent_run_id="parent", node_id="n1", objective="SUBTASK::w", wait=False))
    child_id = result.child_run_id
    assert child_id is not None
    # fire-and-forget：子在 asyncio 任务内注册 + 驱动；轮询等到它出现并落到 write 的
    # awaiting_approval 安全点（真权限求值，非手塞）。
    child_controller = None
    for _ in range(1000):
        child_controller = registry.get(child_id)
        if child_controller is not None and child_controller.run.status is RunStatus.AWAITING_APPROVAL:
            break
        await asyncio.sleep(0.01)
    if child_controller is None or child_controller.run.status is not RunStatus.AWAITING_APPROVAL:
        pytest.fail("child never reached awaiting_approval for its write")
    # DoD④ 端到端：父 full_auto 不传染子——子投影 mode=default，write 才落 ask。
    assert child_controller.run.permission_ctx.mode == "default"

    await asyncio.wait_for(orchestrator.on_parent_terminal("parent"), timeout=10)  # → Cancel(owner) 进子 inbox
    await asyncio.wait_for(orchestrator._child_tasks[child_id], timeout=10)  # 子 wait_for 收 Cancel → 收敛

    final = child_controller.run
    assert final.status is RunStatus.CANCELLED
    assert final.cancel_reason is CancelReason.OWNER
    assert open_tool_use_ids(final.context.items) == ()  # C7：未闭合 write 被回填，无悬空 tool_use
