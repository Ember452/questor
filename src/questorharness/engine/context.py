"""Context shared across a single query run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from questorharness.capabilities.policy.checker import PermissionChecker
from questorharness.capabilities.tools.contract import ToolRegistry
from questorharness.providers.llm.client import SupportsStreamingMessages
from questorharness.runtime.hooks import HookExecutor


PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]

# 协调者运行时上下文消息的首行标记。query_engine 构造该消息、query 回收它,
# 两处共用这一个定义;识别协调者回合靠 QueryContext.coordinator_mode 这个
# 显式标志,而不是嗅探系统提示词的开头一句。
COORDINATOR_CONTEXT_MARKER = "# Coordinator User Context"


@dataclass
class QueryContext:
    """Context shared across a single query run."""

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
    coordinator_mode: bool = False

# questor: allow R7 -- until W8 adds the mirror test
