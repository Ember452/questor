"""Ports injected into tool execution contexts.

Capabilities depend on these protocols only; the provider adapters live in
``providers`` and are injected by the runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from questorharness.contracts.mcp import McpResourceInfo


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
