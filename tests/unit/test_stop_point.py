"""B5/c3：settle_turn 收口到 Stop 点位（单一入口；既有 `settle=` 仅为兼容薄糖）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.settle import TurnBoundary
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface


def _loop(*, settle=None) -> DefaultTurnLoop:  # noqa: ANN001
    return DefaultTurnLoop(
        provider=EchoProvider(),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(),
        tool_for=lambda _name: None,
        workspace_root=Path.cwd(),
        settle=settle,
    )


async def test_settle_kwarg_becomes_one_stop_entry_and_is_invoked_once() -> None:
    seen: list[TurnBoundary] = []

    async def settle(boundary: TurnBoundary) -> None:
        seen.append(boundary)

    loop = _loop(settle=settle)
    assert [entry.descriptor.id for entry in loop._stop.entries] == ["settle-turn"]
    assert loop._stop.entries[0].descriptor.at == "Stop"
    await loop._settle_turn(Run(run_id="r1", budget=Budget(max_turns=1)), 1, None, {}, interrupted=False)
    assert len(seen) == 1 and seen[0].run_id == "r1"


async def test_stop_hook_failure_never_breaks_the_turn() -> None:
    async def boom(_boundary: TurnBoundary) -> None:
        raise RuntimeError("settle exploded")

    loop = _loop(settle=boom)
    # 观察链自己兜异常与 FAILED_ABORT；这里必须不抛。
    await loop._settle_turn(Run(run_id="r2", budget=Budget(max_turns=1)), 2, None, {}, interrupted=False)


def test_cli_surface_registers_settle_as_stop_observe_entry() -> None:
    surface = CliSurface(provider=EchoProvider())
    tool_surface = surface.registry.freeze_for_run("run_stop")
    loop = surface._loop(InProcessEventBus(), asyncio.Event(), tool_surface, run_id="run_stop")
    stop_entries = [entry for entry in loop._stop.entries if entry.descriptor.at == "Stop"]
    assert [entry.descriptor.id for entry in stop_entries] == ["settle-turn"]
    assert stop_entries[0].descriptor.kind.value == "observe"


def test_inspect_view_lists_policy_and_settle_at_closed_points() -> None:
    surface = CliSurface(provider=EchoProvider())
    text = surface.inspect_extensions()
    assert "13 live + 4 reserved" in text
    assert "[UserPromptSubmit]" in text and "react" in text
    assert "[Stop]" in text and "settle-turn" in text
    assert "Notification, Elicitation, TaskUpdated, PlanStep" in text
