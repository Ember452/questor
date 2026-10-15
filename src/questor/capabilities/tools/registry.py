"""L3 tool registry seam (design/03 §6).

Tools register here; the set is *frozen per run* so the model never sees a tool
appear/disappear mid-run (``tools_changed`` applies to the next run). The
concrete registry is P1 (T5)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from questor.contracts.tool import Tool


class ToolRegistry(ABC):
    """Holds the available tools for the next run; add/get only."""

    @abstractmethod
    def register(self, tool: Tool) -> None:
        """Add a tool (new tool = new registration; never mutate existing semantics)."""

    @abstractmethod
    def get(self, name: str) -> Tool | None:
        """Look up a tool by name; ``None`` if unknown."""

    @abstractmethod
    def list_available(self) -> tuple[Tool, ...]:
        """Tools whose ``available()`` is True (feature-flag/credential gating)."""
