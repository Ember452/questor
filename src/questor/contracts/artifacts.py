"""L0 Artifact 契约（ADR-0019；HARD C4/C13）。

工具全文输出不直接进模型/事件/checkpoint；超过预算时只引用内容寻址 artifact。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from questor.contracts.common import JsonObject, freeze, require_aware, utc_now


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """受控持久化后返回给工具/Harness 的不透明引用。"""

    artifact_id: str
    sha256: str
    total_bytes: int
    kind: str
    media_type: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_aware(self.created_at, "ArtifactRef.created_at")
        if not self.sha256 or len(self.sha256) != 64:
            raise ValueError("ArtifactRef.sha256 must be a SHA-256 hex digest")
        if self.total_bytes < 0:
            raise ValueError("ArtifactRef.total_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class OutputBudget:
    """输出长度上限；单位是 UTF-8 bytes，不是 Python chars。"""

    model_result_bytes: int = 16 * 1024
    display_bytes: int = 64 * 1024
    stdout_bytes: int = 1024 * 1024
    stderr_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        # 0/negative 会让“无界”重新进入 prompt/event；None 由调用方显式传默认值处理。
        for name in ("model_result_bytes", "display_bytes", "stdout_bytes", "stderr_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"OutputBudget.{name} must be positive")


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    """给模型的有界结果；全文只能通过 ref 回读。"""

    kind: str
    artifact: ArtifactRef
    preview: str
    total_bytes: int
    truncated: bool
    continuation: JsonObject = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "continuation", freeze(self.continuation))
        if self.kind != "archived_tool_result":
            raise ValueError("ArtifactEnvelope.kind must be archived_tool_result")
        if self.total_bytes != self.artifact.total_bytes:
            raise ValueError("ArtifactEnvelope.total_bytes must match artifact total_bytes")
        if not self.truncated and self.artifact.total_bytes > len(self.preview.encode("utf-8")):
            raise ValueError("untruncated ArtifactEnvelope preview must contain the full result")


__all__ = ["ArtifactEnvelope", "ArtifactRef", "OutputBudget"]
