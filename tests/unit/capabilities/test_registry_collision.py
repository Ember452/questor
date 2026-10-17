"""ToolRegistry 命名冲突守卫的判红用例（C21；`docs/plan/05` T6，C17）。

远程工具若产出与既有工具同名的 spec：拒绝覆盖 + 出声（first-writer-wins），绝不静默顶掉内置工具。
同对象重注册（幂等 reload）不算冲突、不告警。"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from questor.capabilities.tools.registry import ToolRegistry
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(
            name=name,
            description=f"tool {name} doing a specific job here",
            params={"type": "object", "properties": {}},
            capability=Capability.READONLY,
            risk=Risk.LOW,
            read_only=True,
        )

    def available(self) -> bool:
        return True

    async def execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        return ToolResult(status="success")


def test_collision_rejected_existing_kept_and_warned(caplog: pytest.LogCaptureFixture) -> None:
    registry = ToolRegistry()
    a = _StubTool("dup")
    b = _StubTool("dup")
    registry.register(a)
    with caplog.at_level(logging.WARNING, logger="questor.tools"):
        registry.register(b)
    assert registry.get("dup") is a  # 保留先注册者
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.tools"]
    assert any("dup" in m for m in warns)


def test_same_object_re_register_is_not_a_collision(caplog: pytest.LogCaptureFixture) -> None:
    registry = ToolRegistry()
    tool = _StubTool("solo")
    registry.register(tool)
    with caplog.at_level(logging.WARNING, logger="questor.tools"):
        registry.register(tool)  # 幂等 reload，同对象
    assert registry.get("solo") is tool
    assert [r for r in caplog.records if r.name == "questor.tools"] == []
