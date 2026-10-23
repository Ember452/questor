"""Context shared across a single query run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from questorharness.capabilities.policy.checker import PermissionChecker
from questorharness.capabilities.tools.base import ToolRegistry
from questorharness.providers.llm.client import SupportsStreamingMessages
from questorharness.runtime.hooks import HookExecutor


PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]


@dataclass
class QueryContext:
    """Context shared across a query run."""

    api_client: SupportsStreamingMessages
    tool_registry: ToolRegistry
    permission_checker: PermissionChecker
    cwd: Path
    model: str
    system_prompt: str
    max_tokens: int
    effort: str | None = None
    context_window_tokens: int | None = None
    auto_compact_threshold_tokens: int | None = None
    permission_prompt: PermissionPrompt | None = None
    ask_user_prompt: AskUserPrompt | None = None
    max_turns: int | None = 200
    hook_executor: HookExecutor | None = None
    tool_metadata: dict[str, object] | None = None
