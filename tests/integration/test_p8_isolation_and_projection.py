"""P8 C10 + F5（审计 §6/§8）：子 run 故障隔离 + 扇出带外投影"恰一行"。

- C10：子 run 的 provider 抛错 → 子在**自己**账本归一 `run_failed`（ADR-0028），**绝不带崩父**；
  父 `delegate` 拿到 `terminal_status=failed` 并正常收敛（父 completed、非假崩）。
- F5：父子共享一条 bus，父挂**两个并发订阅者**（正是 ADR-0033 修过的多-surface 双投雷区的扇出版）；
  带外投影 observer 对每个里程碑事件仍**恰触发一次**——`peer_started/peer_ended` 不因订阅者翻倍。
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
)
from questor.kernel.events import Envelope, InProcessEventBus
from questor.kernel.run_control import RunController
from questor.state.domain_state import PermissionCtx, Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.run_registry import RunRegistry
from questor.surfaces.subagent_orchestrator import SubagentOrchestrator

_CHILD = "SUBTASK::"


class _ScriptProvider(ProviderPort):
    """父 turn1 → delegate；父有 tool_result → 收敛；子 → 完成或抛（child_fail）。"""

    def __init__(self, *, child_fail: bool) -> None:
        self._child_fail = child_fail

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        msgs = request.messages
        users = [m for m in msgs if m.role is Role.USER]
        last_user = "".join(b.text or "" for b in (users[-1].content if users else ())) if users else ""
        is_child = len(msgs) == 1 and last_user.startswith(_CHILD)
        has_result = any(b.type == "tool_result" for m in msgs for b in m.content)
        if is_child:
            if self._child_fail:
                raise RuntimeError("child provider boom")
            yield StreamChunk(kind="text", text="child-done")
            yield StreamChunk(kind="finish", finish_reason="stop")
        elif has_result:
            yield StreamChunk(kind="text", text="recovered")
            yield StreamChunk(kind="finish", finish_reason="stop")
        else:
            yield StreamChunk(
                kind="tool_call",
                tool_call={"index": 0, "id": "d1", "name": "delegate", "args_delta": '{"objective": "SUBTASK::x"}'},
            )
            yield StreamChunk(kind="finish", finish_reason="tool_calls")


def _parent() -> Run:
    return Run(
        run_id="parent",
        budget=Budget(max_turns=5),
        permission_ctx=PermissionCtx(
            mode="default",
            rules=(PermissionRule(id="ad", tool_pattern="delegate", argument_pattern="*", action="allow"),),
        ),
    )


async def _drive_parent_with_child(tmp_path: Path, *, child_fail: bool) -> tuple[Run, list[Envelope], RunRegistry, InProcessEventBus]:
    surface = CliSurface(workspace_root=tmp_path, provider=_ScriptProvider(child_fail=child_fail), model="test")
    bus = InProcessEventBus(store=None)
    registry = RunRegistry()
    orchestrator = SubagentOrchestrator(surface=surface, store=None, bus=bus, registry=registry)
    seen: list[Envelope] = []
    bus.add_observer(seen.append)

    controller = RunController(_parent())
    registry.register(controller)
    msg = Message(id="m0", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)
    await registry.submit("parent", SubmitMessage(run_id="parent", content=msg), source="t", idempotency_key="submit:parent")
    tool_surface = surface._freeze_surface("parent", [])
    loop = surface._loop(bus, asyncio.Event(), tool_surface, subagent_spawner=orchestrator)
    result = await asyncio.wait_for(loop.drive_controller(controller), timeout=20)
    return result, seen, registry, bus


async def test_child_provider_fault_is_isolated_from_parent(tmp_path: Path) -> None:
    result, seen, _, _ = await _drive_parent_with_child(tmp_path, child_fail=True)
    # 父不被子故障拖崩，正常收敛。
    assert result.status is RunStatus.COMPLETED
    ended = [e for e in seen if e.type == "peer_ended"]
    assert len(ended) == 1 and ended[0].data["terminal_status"] == "failed"
    child_run_id = ended[0].data["child_run_id"]
    assert child_run_id and child_run_id != "parent"
    # 子的 provider 故障归一在子自己的账本里（run_failed），不冒到父。
    assert any(e.run_id == child_run_id and e.type == "run_failed" for e in seen)
    assert not any(e.run_id == "parent" and e.type == "run_failed" for e in seen)


async def test_fanout_out_of_band_projection_fires_exactly_once(tmp_path: Path) -> None:
    # 父子共享 bus，父挂两个并发订阅者（多-surface 双投雷区的扇出版，ADR-0033/pitfalls#5）。
    surface = CliSurface(workspace_root=tmp_path, provider=_ScriptProvider(child_fail=False), model="test")
    bus = InProcessEventBus(store=None)
    registry = RunRegistry()
    orchestrator = SubagentOrchestrator(surface=surface, store=None, bus=bus, registry=registry)
    collected: list[Envelope] = []
    bus.add_observer(collected.append)  # bus 级唯一带外投影（与订阅者数量无关）
    bus.add_subscriber("parent")  # 消费者 1
    bus.add_subscriber("parent")  # 消费者 2 —— 若投影是逐消费者的，peer_ended 会翻倍

    controller = RunController(_parent())
    registry.register(controller)
    msg = Message(id="m0", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)
    await registry.submit("parent", SubmitMessage(run_id="parent", content=msg), source="t", idempotency_key="submit:parent")
    tool_surface = surface._freeze_surface("parent", [])
    loop = surface._loop(bus, asyncio.Event(), tool_surface, subagent_spawner=orchestrator)
    result = await asyncio.wait_for(loop.drive_controller(controller), timeout=20)

    assert result.status is RunStatus.COMPLETED
    # 两个订阅者下里程碑事件仍恰投一次（不翻倍）。
    assert sum(1 for e in collected if e.type == "peer_started") == 1
    assert sum(1 for e in collected if e.type == "peer_ended") == 1
    assert sum(1 for e in collected if e.type == "run_completed") == 2  # 父 + 子各一
