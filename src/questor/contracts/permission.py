"""L0 permission vocabulary（design/01 §6；ADR-0006/0014/0015）。

决策类型与 outcome 是跨 kernel/provider/surface 共享的纯数据。放在 L0 是为了让
capability floor 与 permission policy 都能引用同一决策语义，而彼此不形成 import 环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PermissionDecision(StrEnum):
    """三态权限决策；`deny` 不计入失败重试（design/01 §6）。"""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionOutcome:
    """权限/capability floor 的统一可审计结果。"""

    decision: PermissionDecision
    reason: str
    args_summary: str
    warnings: tuple[str, ...] = ()
    floor_applied: str | None = None
    candidate_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("PermissionOutcome requires a reason")
        if not self.args_summary.strip():
            raise ValueError("PermissionOutcome requires a non-empty args summary")


__all__ = ["PermissionDecision", "PermissionOutcome"]
