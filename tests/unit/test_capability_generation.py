"""P9 T5：能力名册 generation → loop 发 live-only ``tools_changed``（ADR-0046 决策5；"字段≠gate"的 gate）。

真依赖判据：``generation`` 计数器存在 ≠ loop 消费它——本测钉 ① ToolRegistry 增删 bump generation、
② loop 的 ``_maybe_announce_capability`` 真在 generation 变化时发一条 live-only ``tools_changed``
（不入库、只转给订阅者），无变化时不发。
"""

from __future__ import annotations

import asyncio

from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import ToolRegistry
from questor.contracts.events import EventType
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.state.domain_state import Run


def test_registry_generation_bumps_on_register_and_unregister() -> None:
    reg = ToolRegistry()
    base = reg.generation
    reg.register(ReadTool())
    assert reg.generation == base + 1
    reg.unregister("read")
    assert reg.generation == base + 2


def test_registry_unregister_unknown_does_not_bump() -> None:
    reg = ToolRegistry()
    base = reg.generation
    reg.unregister("nope")
    assert reg.generation == base


def test_loop_emits_live_only_tools_changed_on_generation_bump() -> None:
    counter = {"gen": 0}

    async def _go() -> None:
        bus = InProcessEventBus()  # store=None：live-only 事件本就不入库
        loop = DefaultTurnLoop(
            provider=EchoProvider(),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=bus,
            tool_for=lambda _name: None,
            capability_probe=lambda: counter["gen"],
        )
        run = Run(run_id="r1")
        queue = bus.add_subscriber(run.run_id)

        # 无变化 → 不发。
        await loop._maybe_announce_capability(run, 1)
        assert queue.empty()

        # generation bump → 发一条 live-only tools_changed(domain=tools)。
        counter["gen"] = 1
        await loop._maybe_announce_capability(run, 1)
        env = queue.get_nowait()
        assert env.type == EventType.TOOLS_CHANGED
        assert env.data["domain"] == "tools"

        # 回到无变化 → 再不发（观测已对齐）。
        await loop._maybe_announce_capability(run, 1)
        assert queue.empty()

    asyncio.run(_go())
