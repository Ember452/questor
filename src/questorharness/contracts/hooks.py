"""Hook event and result vocabulary shared across engine layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class HookEvent(str, Enum):
    """Events that can trigger hooks."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    NOTIFICATION = "notification"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"


@dataclass(frozen=True)
class HookResult:
    """Result from a single hook execution."""

    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregatedHookResult:
    """Aggregated result for a hook event."""

    results: list[HookResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Return whether any hook blocked continuation."""
        return any(result.blocked for result in self.results)

    @property
    def reason(self) -> str:
        """Return the first blocking reason, if any."""
        for result in self.results:
            if result.blocked:
                return result.reason or result.output
        return ""


class CommandHookDefinition(BaseModel):
    """A hook that executes a shell command."""

    type: Literal["command"] = "command"
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class PromptHookDefinition(BaseModel):
    """A hook that asks the model to validate a condition."""

    type: Literal["prompt"] = "prompt"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = True
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class HttpHookDefinition(BaseModel):
    """A hook that POSTs the event payload to an HTTP endpoint."""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class AgentHookDefinition(BaseModel):
    """A hook that performs a deeper model-based validation."""

    type: Literal["agent"] = "agent"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=1200)
    matcher: str | None = None
    block_on_failure: bool = True
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


HookDefinition = (
    CommandHookDefinition
    | PromptHookDefinition
    | HttpHookDefinition
    | AgentHookDefinition
)
