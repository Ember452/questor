"""L0 ProcessRunner 契约（ADR-0018；HARD C1/C8/C10）。

工具只提出结构化进程请求；argv 包装、env scrub、timeout、进程树清理、artifact 落盘
全部由 Harness-owned adapter 完成，避免 capability/tools 直接拥有 spawn 能力。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from questor.contracts.artifacts import ArtifactRef

if TYPE_CHECKING:
    from questor.contracts.tool import Capability


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    """一次受控子进程请求；`argv[0]` 必须是已解析的绝对程序路径。"""

    capability: Capability
    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float
    declared_env_names: tuple[str, ...] = ()
    stdout_limit: int = 1024 * 1024
    stderr_limit: int = 1024 * 1024

    def __post_init__(self) -> None:
        # timeout 必须 finite positive；缺 timeout 不是“无超时”，而是注册/调用期错误。
        if not self.timeout_s > 0:
            raise ValueError("ProcessRequest.timeout_s must be positive")
        if not self.argv or not self.argv[0]:
            raise ValueError("ProcessRequest.argv[0] is required")
        if not Path(self.argv[0]).is_absolute():
            raise ValueError("ProcessRequest.argv[0] must be absolute")
        if self.stdout_limit <= 0 or self.stderr_limit <= 0:
            raise ValueError("ProcessRequest output limits must be positive")


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """结构化进程事实；失败也返回结果，绝不把 subprocess exception 抛穿循环。"""

    exit_code: int | None
    stdout_text: str
    stderr_text: str
    timed_out: bool = False
    process_tree_killed: bool = False
    sandbox_backend: str = "none"
    confinement: str = "none"
    warning: str | None = None
    env_scrubbed: tuple[str, ...] = ()
    stdout_artifact: ArtifactRef | None = None
    stderr_artifact: ArtifactRef | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.timed_out and self.exit_code is None:
            raise ValueError("timed-out ProcessResult must include final exit_code")
        if self.error and self.exit_code is not None:
            raise ValueError("error ProcessResult cannot claim a completed exit_code")


@runtime_checkable
class ProcessRunnerPort(Protocol):
    """Harness-owned process seam。"""

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """执行受控进程；launcher/wrap failure 必须转成带 error 的 ProcessResult。"""


__all__ = ["ProcessRequest", "ProcessResult", "ProcessRunnerPort"]
