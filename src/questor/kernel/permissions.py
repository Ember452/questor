"""L2 权限引擎兼容导入点（ADR-0014）。

真正实现与配置词汇已迁至 ``permission_policy``；本模块只保留历史 import path，避免
同时存在第二套引擎语义。调用方应构造 ``PermissionEvaluation``，权限配置只来自 PermissionCtx。
"""

from __future__ import annotations

from questor.kernel.permission_policy import (
    DefaultPermissionEngine,
    PermissionDecision,
    PermissionEvaluation,
    PermissionOutcome,
    evaluate_permission,
)

__all__ = [
    "DefaultPermissionEngine",
    "PermissionDecision",
    "PermissionEvaluation",
    "PermissionOutcome",
    "evaluate_permission",
]
