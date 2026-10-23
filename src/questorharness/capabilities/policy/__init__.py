"""Permission helpers for QuestorHarness."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from questorharness.capabilities.policy.checker import PermissionChecker, PermissionDecision
    from questorharness.contracts.policy import PermissionMode

__all__ = ["PermissionChecker", "PermissionDecision", "PermissionMode"]


def __getattr__(name: str):
    if name in {"PermissionChecker", "PermissionDecision"}:
        from questorharness.capabilities.policy.checker import PermissionChecker, PermissionDecision

        return {
            "PermissionChecker": PermissionChecker,
            "PermissionDecision": PermissionDecision,
        }[name]
    if name == "PermissionMode":
        from questorharness.contracts.policy import PermissionMode

        return PermissionMode
    raise AttributeError(name)

# questor: allow R4 -- until W8 facade split
