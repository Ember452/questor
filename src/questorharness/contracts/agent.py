"""Agent definition projection shared with capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentProfile:
    """The subset of an agent definition a tool needs to launch it."""

    name: str
    model: str | None = None
    system_prompt: str | None = None
    permissions: list[str] = field(default_factory=list)
