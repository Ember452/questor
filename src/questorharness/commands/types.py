"""Command value types shared by the slash command registry and handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Iterable

from questorharness.engine.query_engine import QueryEngine
from questorharness.runtime.session.backend import DEFAULT_SESSION_BACKEND, SessionBackend

if TYPE_CHECKING:
    from questorharness.capabilities.tools.base import ToolRegistry
    from questorharness.state import AppStateStore


@dataclass
class CommandResult:
    """Result returned by a slash command."""

    message: str | None = None
    should_exit: bool = False
    clear_screen: bool = False
    replay_messages: list | None = None  # 在 TUI 中回放的 ConversationMessage 列表
    continue_pending: bool = False
    continue_turns: int | None = None
    refresh_runtime: bool = False
    submit_prompt: str | None = None
    submit_model: str | None = None


@dataclass(frozen=True)
class MemoryCommandBackend:
    """Storage backend used by the generic ``/memory`` slash command."""

    label: str
    default_type: str
    default_category: str
    get_memory_dir: Callable[[], Path]
    get_entrypoint: Callable[[], Path]
    list_files: Callable[[], list[Path]]
    add_entry: Callable[[str, str], Path]
    remove_entry: Callable[[str], bool]


@dataclass
class CommandContext:
    """Context available to command handlers."""

    engine: QueryEngine
    hooks_summary: str = ""
    mcp_summary: str = ""
    plugin_summary: str = ""
    cwd: str = "."
    tool_registry: ToolRegistry | None = None
    app_state: AppStateStore | None = None
    session_backend: SessionBackend = DEFAULT_SESSION_BACKEND
    session_id: str | None = None
    extra_skill_dirs: Iterable[str | Path] | None = None
    extra_plugin_roots: Iterable[str | Path] | None = None
    memory_backend: MemoryCommandBackend | None = None
    include_project_memory: bool = True


CommandHandler = Callable[[str, CommandContext], Awaitable[CommandResult]]


@dataclass
class SlashCommand:
    """Definition of a slash command."""

    name: str
    description: str
    handler: CommandHandler
    remote_invocable: bool = True
    remote_admin_opt_in: bool = False
    aliases: tuple[str, ...] = ()
