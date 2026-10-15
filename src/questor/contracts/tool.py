"""L0 工具契约：``ToolSpec`` + ``Tool``/``ToolResult`` + ``ToolContext``
（design/03；HARD C1/C4/C8/C9）。策略只能"提议调用工具 X + 参数"，**校验/权限/沙箱/
超时/记账全在 Harness**。P0 固定接口形状；read 的实现见 P1(T5)。工具绝不 import
provider/store/sandbox/UI（C1）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from questor.contracts.common import JsonObject
from questor.contracts.errors import ErrorEntry

if TYPE_CHECKING:
    from questor.contracts.artifacts import ArtifactRef
    from questor.contracts.process import ProcessRequest, ProcessResult


class Capability(StrEnum):
    """工具能力类别，决定默认风险档与是否需要沙箱（design/03 §7）。"""

    READONLY = "readonly"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    MEMORY = "memory"


class Risk(StrEnum):
    """默认风险等级；与 capability 共同决定沙箱档与权限默认决策。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """工具的注册规格（L0 契约，注册进 L3）。新增工具=加注册，改语义=契约变更。"""

    name: str
    description: str
    params: JsonObject  # 参数 JSON-Schema，Harness 据此做结构校验（C8）
    capability: Capability
    risk: Risk
    read_only: bool = False  # 权威布尔；缺 metadata 一律 fail-closed 视为非只读
    available: bool = True
    timeout_s: float | None = None  # None → Budget 默认；0/负值注册期拒绝
    parallel_safe: bool = False  # 仅 schema 占位，完整并行到 P5（ROADMAP §2.5）
    approval_mode: str | None = None  # MCP：只收紧不放宽，unknown→deny（03 §11）
    orchestrator: bool = False  # 嵌套/子代理工具：不参与 gate（03 §11）
    barrier: bool = False  # 同批独占
    description_max_chars: int = 2000  # 描述长度上限（防超长/注入面）

    def __post_init__(self) -> None:
        # 超时必须是正数；None 表示“采用 run 级默认”，不是无限等待。
        if self.timeout_s is not None and not self.timeout_s > 0:
            raise ValueError("ToolSpec.timeout_s must be positive")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具返回：``result`` 给模型、``display`` 给人（卡片）。"""

    status: str  # success | error | critical_error
    result: Any | None = None
    display: Any | None = None
    files: tuple[str, ...] = ()
    artifact: JsonObject | None = None
    error: ErrorEntry | None = None


@runtime_checkable
class ToolContext(Protocol):
    """交给工具的**受控**能力（design/03 §2；ADR-0018/0019）。

    不给裸 filesystem/vector/provider/sandbox 句柄。工具只能返回 `ToolResult`，
    进程与 artifact 都必须经 Harness port，状态写入由 Harness reduce 完成。
    """

    tool_call_id: str
    workspace_root: Path
    cwd: Path

    def is_cancelled(self) -> bool: ...

    def report_progress(self, message: str) -> None: ...

    def emit_progress(self, payload: JsonObject) -> None: ...  # 仅瞬态观测事件

    def declare_env_passthrough(self, name: str) -> None: ...

    async def run_process(self, request: ProcessRequest) -> ProcessResult: ...

    async def put_artifact(
        self,
        content: bytes,
        *,
        kind: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef: ...


class Tool(ABC):
    """工具实现基类。每个具体工具声明自己的 ``spec``。"""

    spec: ToolSpec

    @abstractmethod
    def available(self) -> bool:
        """动态可用性（特性开关/凭据缺失时隐藏）。"""

    @abstractmethod
    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """纯业务逻辑；沙箱/权限/超时由 Harness 在其外层包裹（C8）。"""


__all__ = [
    "Capability",
    "Risk",
    "ToolSpec",
    "ToolResult",
    "ToolContext",
    "Tool",
]
