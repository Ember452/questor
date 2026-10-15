"""L2 permission engine seam (design/03 §3/§4; HARD C8/C9).

Three-valued ``allow/ask/deny`` is *decided* here (pure), never enforced here:
enforcement points live in the loop + tool executor. Full 8-step evaluation +
non-overridable sensitive-path denylist (with realpath/expanduser/symlink) is P1
(T6), adapted from DeepCode ``core/harness/permissions.py``."""

from __future__ import annotations

from abc import ABC, abstractmethod

from questor.contracts.common import JsonObject


class PermissionEngine(ABC):
    """Decides allow/ask/deny for a proposed tool call (+ a readable reason)."""

    @abstractmethod
    def evaluate(self, tool_name: str, arguments: JsonObject | None = None) -> tuple[str, str]:
        """Return ``(decision, reason)``; ``deny`` never counts as a failed retry."""
