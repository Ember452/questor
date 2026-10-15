"""L5 Port protocols (design/00 §3.1; HARD C1/C4/C9/C12).

Ports are abstract (`Protocol`) and defined at the innermost layer; concrete
adapters (LiteLLM, SQLite, sandbox backends) live in :mod:`questor.providers` and
are *injected* into the kernel. The kernel imports only these protocols, never an
implementation (C1/C14). P0 fixes signatures; bodies are implemented from P1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from questor.contracts.common import JsonObject
from questor.contracts.state_schema import Message
from questor.contracts.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    system: str | None = None
    stream: bool = True
    settings: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One normalized streaming increment (kernel maps to *_delta / tool_use)."""

    kind: str  # text | reasoning | tool_call | usage | finish
    text: str | None = None
    tool_call: JsonObject | None = None
    usage: JsonObject | None = None
    finish_reason: str | None = None
    raw: Any | None = None


@runtime_checkable
class ProviderPort(Protocol):
    async def stream(self, request: ProviderRequest):  # -> AsyncIterator[StreamChunk]
        """Yield normalized chunks; the caller classifies errors (ADR-0010)."""
        ...


@runtime_checkable
class StorePort(Protocol):
    """Append-only event log + snapshot read/write (design/01 §9; ADR-0005/0011).

    The ONLY persistence path; strategies hold no raw handle (C4)."""

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int: ...

    async def replay(
        self, run_id: str, after_seq: int, limit: int | None = None
    ) -> list[JsonObject]: ...

    async def sequence_head(self, run_id: str) -> int: ...

    async def save_checkpoint(self, checkpoint: JsonObject) -> None: ...

    async def latest_checkpoint(self, run_id: str) -> JsonObject | None: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new(self, prefix: str) -> str: ...


@runtime_checkable
class SandboxPort(Protocol):
    """Pluggable execution isolation + capability probes (design/03 §4; C9/T4).

    ``fences_*`` report what the backend actually isolates; when a capability is
    absent the Harness fail-closes (exec/high => deny) rather than run raw."""

    def fences_writes(self) -> bool: ...

    def fences_network(self) -> bool: ...

    def isolates_process_tree(self) -> bool: ...

    def wrap_argv(self, capability: str, argv: tuple[str, ...]) -> tuple[str, ...]: ...


__all__ = [
    "ProviderRequest",
    "StreamChunk",
    "ProviderPort",
    "StorePort",
    "Clock",
    "IdGenerator",
    "SandboxPort",
]
