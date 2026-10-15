"""L0 tool contract: ``ToolSpec`` + ``Tool``/``ToolResult`` + ``ToolContext``
(design/03; HARD C1/C4/C8/C9). The strategy only *proposes* a call; validation,
permission, sandbox, timeout and accounting all live in the Harness.

P0 fixes the interface shapes; the read tool implementation is P1 (T5). Tools
must not import provider/store/sandbox/UI (C1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Protocol, runtime_checkable

from questor.contracts.common import JsonObject
from questor.contracts.errors import ErrorEntry


class Capability(StrEnum):
    READONLY = "readonly"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    MEMORY = "memory"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    params: JsonObject  # JSON-Schema for argument shape (validated by Harness, C8)
    capability: Capability
    risk: Risk
    read_only: bool = False  # authoritative flag; missing metadata => fail-closed
    available: bool = True
    parallel_safe: bool = False  # schema placeholder until P5 (ROADMAP §2.5)
    approval_mode: str | None = None  # MCP: may only tighten (03 §11)
    orchestrator: bool = False  # nested/sub-agent tool; not gated (03 §11)
    barrier: bool = False  # exclusive within a batch
    description_max_chars: int = 1024


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: str  # success | error | critical_error
    result: Any | None = None  # for the model
    display: Any | None = None  # for the human (card)
    files: tuple[str, ...] = ()
    artifact: JsonObject | None = None
    error: ErrorEntry | None = None


@runtime_checkable
class ToolContext(Protocol):
    """The *controlled* capabilities a tool may touch (design/03 §2, T1).

    No raw filesystem/vector handle. A tool may only *return* a ``ToolResult``;
    it must never submit a Command or mutate Domain_State (T1 -> single writer)."""

    workspace_root: PurePosixPath

    def is_cancelled(self) -> bool: ...

    def report_progress(self, message: str) -> None: ...

    def emit_progress(self, payload: JsonObject) -> None: ...  # transient only


class Tool(ABC):
    spec: ToolSpec  # each concrete tool declares its own spec

    @abstractmethod
    def available(self) -> bool:
        """Dynamic availability (feature flag / missing credential => hide)."""

    @abstractmethod
    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """Pure business logic; sandbox/permission/timeout wrap this in Harness."""


__all__ = [
    "Capability",
    "Risk",
    "ToolSpec",
    "ToolResult",
    "ToolContext",
    "Tool",
]
