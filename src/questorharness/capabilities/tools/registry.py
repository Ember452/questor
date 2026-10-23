"""Built-in tool discovery and the derived capability index.

Two things live here:

* ``discover_builtin_tools()`` imports every module under
  ``capabilities/tools`` and maps class name to class, so the import block no
  longer has to be edited when a tool is added;
* ``capability_index()`` derives an immutable view of what the engine may assume
  (read-only, compaction, artifact keys, carry-over category) from the
  declarations on the tools themselves.

The registration order is still explicit. It decides the order of ``tools[]`` in
every prompt, so it is data, not a side effect of directory walking.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

import questorharness.capabilities.tools as _tools_package
from questorharness.capabilities.tools.base import BaseTool, ToolRegistry

# Registration order is the prompt order. Adding a tool means one new module plus
# one line here; scripts/guards/check_tool_radius.py fails when a discovered tool
# is missing from this tuple.
#
# Growth note (plan 01 W11 / P5): this tuple is linear in tool count and the file
# has a 250-line budget. Past ~100 tools the explicit order should become
# "sorted by family + an exception table for the few tools whose order matters".
_BUILTIN_CLASSES: tuple[str, ...] = (
    "BashTool",
    "AskUserQuestionTool",
    "FileReadTool",
    "FileWriteTool",
    "FileEditTool",
    "NotebookEditTool",
    "LspTool",
    "McpAuthTool",
    "GlobTool",
    "GrepTool",
    "ImageToTextTool",
    "ImageGenerationTool",
    "SkillTool",
    "ToolSearchTool",
    "WebFetchTool",
    "WebSearchTool",
    "ConfigTool",
    "BriefTool",
    "SleepTool",
    "EnterWorktreeTool",
    "ExitWorktreeTool",
    "TodoWriteTool",
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "CronCreateTool",
    "CronListTool",
    "CronDeleteTool",
    "CronToggleTool",
    "RemoteTriggerTool",
    "TaskCreateTool",
    "TaskGetTool",
    "TaskListTool",
    "TaskStopTool",
    "TaskOutputTool",
    "TaskUpdateTool",
    "AgentTool",
    "SendMessageTool",
    "TeamCreateTool",
    "TeamDeleteTool",
)

# Tools that only exist when an MCP manager is provided; they are registered
# separately and never appear in the discovery parity check.
CONDITIONAL_CLASSES: frozenset[str] = frozenset(
    {"ListMcpResourcesTool", "ReadMcpResourceTool", "McpToolAdapter"}
)


class ToolDiscoveryError(RuntimeError):
    """Raised when discovery and the explicit registration order disagree."""


class UndeclaredToolError(RuntimeError):
    """Raised when a registered tool carries no ``capabilities`` declaration."""


@dataclass(frozen=True)
class CapabilityIndex:
    """Immutable view derived from the per-tool declarations."""

    by_name: Mapping[str, object]
    read_only_tools: frozenset[str]
    compactable_tools: frozenset[str]
    by_remember_key: Mapping[str, frozenset[str]]


@lru_cache(maxsize=1)
def discover_builtin_tools() -> dict[str, type[BaseTool]]:
    """Return ``{class name: BaseTool subclass}`` for every module in the package."""
    found: dict[str, type[BaseTool]] = {}
    for module_info in pkgutil.walk_packages(
        _tools_package.__path__, prefix=f"{_tools_package.__name__}."
    ):
        module = importlib.import_module(module_info.name)
        for value in vars(module).values():
            if not isinstance(value, type) or not issubclass(value, BaseTool):
                continue
            if value is BaseTool:
                continue
            existing = found.get(value.__name__)
            if existing is not None and existing is not value:
                raise ToolDiscoveryError(f"duplicate tool class name: {value.__name__}")
            found[value.__name__] = value
    return found


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry in the declared order."""
    discovered = discover_builtin_tools()
    missing = [name for name in _BUILTIN_CLASSES if name not in discovered]
    if missing:
        raise ToolDiscoveryError(f"declared tools were not discovered: {', '.join(missing)}")
    unregistered = sorted(
        set(discovered) - set(_BUILTIN_CLASSES) - set(CONDITIONAL_CLASSES)
    )
    if unregistered:
        raise ToolDiscoveryError(
            "discovered but not registered: " + ", ".join(unregistered)
        )

    registry = ToolRegistry()
    for class_name in _BUILTIN_CLASSES:
        registry.register(discovered[class_name]())
    if mcp_manager is not None:
        from questorharness.capabilities.tools.mcp.list_mcp_resources_tool import (
            ListMcpResourcesTool,
        )
        from questorharness.capabilities.tools.mcp.mcp_tool import McpToolAdapter
        from questorharness.capabilities.tools.mcp.read_mcp_resource_tool import (
            ReadMcpResourceTool,
        )

        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


@lru_cache(maxsize=1)
def capability_index() -> CapabilityIndex:
    """Derive the immutable capability view from the built-in registry.

    A tool without a declaration fails loudly: silently treating an undeclared
    tool as read-only or compactable is exactly the behaviour change this index
    exists to prevent.
    """
    by_name: dict[str, object] = {}
    by_remember: dict[str, set[str]] = {}
    read_only: set[str] = set()
    compactable: set[str] = set()
    for tool in create_default_tool_registry(None).list_tools():
        capabilities = getattr(tool, "capabilities", None)
        if capabilities is None:
            raise UndeclaredToolError(
                f"{type(tool).__name__} ({tool.name}) has no capabilities declaration"
            )
        by_name[tool.name] = capabilities
        if capabilities.read_only_by_default:
            read_only.add(tool.name)
        if capabilities.keep_in_compaction:
            compactable.add(tool.name)
        if capabilities.remember_as:
            by_remember.setdefault(capabilities.remember_as, set()).add(tool.name)
    return CapabilityIndex(
        by_name=MappingProxyType(by_name),
        read_only_tools=frozenset(read_only),
        compactable_tools=frozenset(compactable),
        by_remember_key=MappingProxyType(
            {key: frozenset(names) for key, names in by_remember.items()}
        ),
    )


def read_only_tool_names() -> frozenset[str]:
    """Return the tools whose default invocation is read-only."""
    return capability_index().read_only_tools


def compactable_tool_names() -> frozenset[str]:
    """Return the tools whose results survive compaction."""
    return capability_index().compactable_tools


def tool_names_for(remember_key: str) -> frozenset[str]:
    """Return the tools registered under one carry-over category."""
    return capability_index().by_remember_key.get(remember_key, frozenset())
