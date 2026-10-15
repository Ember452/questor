"""L0 SandboxDescriptor（ADR-0015；HARD C9/C17）。

只描述后端**真实**提供的隔离能力。capability floor 必须依赖这里的能力事实，不能把
“有 Job Object/能杀进程树”误写成“有文件系统写围栏”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from questor.contracts.common import JsonObject, freeze


class SandboxBackend(StrEnum):
    """受支持的 sandbox backend 标识。"""

    SEATBELT = "seatbelt"
    BWRAP = "bwrap"
    JOB = "job"
    NONE = "none"


class Confinement(StrEnum):
    """隔离完整度。`partial` 绝不是 full，调用方必须按缺失能力加严。"""

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SandboxDescriptor:
    """后端能力探针结果；所有字段都应是可审计、可重放的事实。"""

    backend: SandboxBackend
    confinement: Confinement
    fences_writes: bool
    fences_network: bool
    isolates_process_tree: bool
    limitation: str
    workspace_profile: JsonObject = field(default_factory=dict)
    executable_path: str | None = None

    def __post_init__(self) -> None:
        # profile 会被跨状态共享，必须深冻结（HARD C2）。
        object.__setattr__(self, "workspace_profile", freeze(self.workspace_profile))
        if not self.limitation.strip():
            raise ValueError("SandboxDescriptor requires an honest limitation")

        # full 的含义只用于真有文件/进程边界的 seatbelt/bwrap；Job Object 永远不是 full。
        if self.confinement is Confinement.FULL:
            if self.backend not in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP}:
                raise ValueError("full confinement requires seatbelt or bwrap")
            if not self.fences_writes or not self.isolates_process_tree:
                raise ValueError("full confinement must fence writes and isolate the process tree")
        if self.confinement is Confinement.NONE and any(
            (self.fences_writes, self.fences_network, self.isolates_process_tree)
        ):
            raise ValueError("none confinement cannot claim isolation capabilities")
        if self.backend is SandboxBackend.NONE and self.confinement is not Confinement.NONE:
            raise ValueError("none backend must report none confinement")
        if self.backend is SandboxBackend.JOB:
            if self.confinement is not Confinement.PARTIAL:
                raise ValueError("job backend must report partial confinement")
            if self.fences_writes:
                raise ValueError("job backend must not claim write fencing")


@runtime_checkable
class SandboxPort(Protocol):
    """Sandbox 能力探针与包装接缝（ADR-0015/0018）。

    `describe()` 是安全判断唯一入口；旧布尔方法只保留为 legacy 兼容。`wrap_*` 必须诚实：
    给不出承诺的隔离就要抛错/返回失败，不能静默 passthrough。
    """

    def describe(self) -> SandboxDescriptor: ...

    def wrap_argv(
        self,
        capability: str,
        argv: tuple[str, ...],
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]: ...


__all__ = ["Confinement", "SandboxBackend", "SandboxDescriptor", "SandboxPort"]
