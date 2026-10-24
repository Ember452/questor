"""Tool abstractions and the capability declarations every tool must carry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from questorharness.capabilities.ports import (
        HookRuntime,
        LlmToolRuntime,
        LspRuntime,
        SandboxRuntime,
        SubagentRuntime,
        TaskRuntime,
    )


@dataclass(frozen=True)
class ToolCapabilities:
    """What the rest of the engine may assume about a tool, declared once.

    Before this type existed the same facts lived in four hand-maintained lists
    (compaction, coordinator, swarm permissions, tool carry-over), so adding a
    tool meant editing five files. Every field defaults to the safe answer; a
    tool still has to carry an explicit ``capabilities = ToolCapabilities(...)``
    line, which ``scripts/guards/check_tool_radius.py`` asserts.
    """

    read_only_by_default: bool = False
    keep_in_compaction: bool = False
    artifact_keys: tuple[str, ...] = ()
    remember_as: str | None = None


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""

    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    hook_executor: HookRuntime | None = None
    sandbox: SandboxRuntime | None = None
    llm: LlmToolRuntime | None = None
    lsp: LspRuntime | None = None
    tasks: TaskRuntime | None = None
    subagents: SubagentRuntime | None = None


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all QuestorHarness tools."""

    name: str
    description: str
    input_model: type[BaseModel]
    capabilities: ClassVar[ToolCapabilities]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema expected by the Anthropic Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> BaseTool | None:
        """Remove a tool by name and return it (``None`` when absent).

        The public face for teardown; callers must not reach into the
        registry's internal mapping to drop a tool.
        """
        return self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def to_api_schema(self) -> list[dict[str, Any]]:
        """Return all tool schemas in API format."""
        return [tool.to_api_schema() for tool in self._tools.values()]
