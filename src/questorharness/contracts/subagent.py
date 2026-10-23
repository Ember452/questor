"""Subagent vocabulary shared by capabilities, runtime and surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BackendType = Literal["subprocess", "in_process", "tmux", "iterm2"]
"""All supported backend types."""

PaneId = str
"""Opaque identifier for a terminal pane managed by a backend."""


@dataclass
class SpawnResult:
    """Result from spawning a teammate."""

    task_id: str
    """Task ID in the task manager."""

    agent_id: str
    """Unique agent identifier (format: agentName@teamName)."""

    backend_type: BackendType
    """The backend used to spawn this agent."""

    success: bool = True
    error: str | None = None

    pane_id: PaneId | None = None
    """Pane ID for pane-based backends (tmux / iTerm2)."""


@dataclass
class TeammateMessage:
    """Message to send to a teammate."""

    text: str
    from_agent: str
    color: str | None = None
    timestamp: str | None = None
    summary: str | None = None

# questor: allow R7 -- until W8 adds the mirror test
