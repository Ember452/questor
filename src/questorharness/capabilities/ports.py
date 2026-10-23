"""Ports injected into tool execution contexts.

Capabilities depend on these protocols only; the provider adapters live in
``providers`` and are injected by the runtime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from questorharness.contracts.agent import AgentProfile
from questorharness.contracts.hooks import AggregatedHookResult, HookEvent
from questorharness.contracts.mcp import McpResourceInfo
from questorharness.contracts.subagent import SpawnResult
from questorharness.contracts.task import TaskRecord, TaskStatus, TaskType


CompletionListener = Callable[[TaskRecord], Awaitable[None]]


@runtime_checkable
class SandboxSessionPort(Protocol):
    """Subset of the Docker sandbox session used by filesystem tools."""

    is_running: bool

    async def exec_command(self, cmd: list[str], **kwargs: Any) -> Any: ...


@runtime_checkable
class SandboxRuntime(Protocol):
    """Sandbox probing and path validation."""

    def is_active(self) -> bool: ...

    def validate_path(self, path: Path, cwd: Path) -> tuple[bool, str]: ...

    def session(self) -> SandboxSessionPort | None: ...


@runtime_checkable
class McpClientPort(Protocol):
    """Subset of the MCP client manager used by tool adapters."""

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> str: ...

    def list_resources(self) -> list[McpResourceInfo]: ...

    async def read_resource(self, server: str, uri: str) -> str: ...


@runtime_checkable
class LspRuntime(Protocol):
    """Code-intelligence helpers used by the lsp tool."""

    def workspace_symbol_search(self, root: Path, query: str) -> Any: ...

    def list_document_symbols(self, file_path: Path) -> Any: ...

    def go_to_definition(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any: ...

    def find_references(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any: ...

    def hover(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any: ...


@runtime_checkable
class LlmToolRuntime(Protocol):
    """LLM helpers needed by model-facing tools."""

    def normalize_openai_base_url(self, base_url: str) -> str: ...

    def build_codex_headers(self, auth_token: str) -> dict[str, str]: ...

    def resolve_codex_url(self, base_url: str) -> str: ...

    async def describe_image(
        self,
        *,
        image_data: str,
        media_type: str,
        prompt: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int,
    ) -> str: ...


@runtime_checkable
class TaskRuntime(Protocol):
    """Background task service consumed by the task and agent tools."""

    async def create_shell_task(
        self,
        *,
        command: str | None = None,
        description: str,
        cwd: Path,
        task_type: TaskType = "local_bash",
        env: dict[str, str] | None = None,
        argv: list[str] | None = None,
    ) -> TaskRecord: ...

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: Path,
        model: str | None = None,
        api_key: str | None = None,
    ) -> TaskRecord: ...

    def get_task(self, task_id: str) -> TaskRecord | None: ...

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]: ...

    def update_task(
        self,
        task_id: str,
        *,
        description: str | None = None,
        progress: int | None = None,
        status_note: str | None = None,
    ) -> TaskRecord: ...

    async def stop_task(self, task_id: str) -> TaskRecord: ...

    async def write_to_task(self, task_id: str, data: str) -> None: ...

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str: ...

    def register_completion_listener(self, listener: CompletionListener) -> Callable[[], None]: ...


@runtime_checkable
class SubagentRuntime(Protocol):
    """Agent definitions, spawning, messaging and team membership."""

    def resolve_profile(self, name: str) -> AgentProfile | None: ...

    async def spawn(
        self,
        *,
        name: str,
        team: str,
        prompt: str,
        cwd: str,
        model: str | None = None,
        command: str | None = None,
        system_prompt: str | None = None,
        permissions: list[str] | None = None,
        task_type: str = "local_agent",
    ) -> SpawnResult: ...

    async def send_message(self, agent_id: str, *, text: str, from_agent: str = "coordinator") -> None: ...

    def create_team(self, name: str, description: str = "") -> str: ...

    def delete_team(self, name: str) -> None: ...

    def attach_agent(self, team: str, task_id: str) -> None: ...


@runtime_checkable
class HookRuntime(Protocol):
    """Hook execution consumed by compaction and subagent events."""

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult: ...
