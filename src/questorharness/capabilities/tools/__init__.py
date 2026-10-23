"""Model-visible tool capabilities.

The facade is lazy: importing it does not import the forty-plus tool modules.
Accessing ``create_default_tool_registry`` loads them on demand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from questorharness.capabilities.tools.base import (
        BaseTool,
        ToolExecutionContext,
        ToolRegistry,
        ToolResult,
    )

__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]


def __getattr__(name: str) -> Any:
    if name in {"BaseTool", "ToolExecutionContext", "ToolRegistry", "ToolResult"}:
        from questorharness.capabilities.tools import base

        return getattr(base, name)
    if name == "create_default_tool_registry":
        from questorharness.capabilities.tools.registry import create_default_tool_registry

        return create_default_tool_registry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

