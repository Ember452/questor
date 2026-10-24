"""Permission vocabulary shared across engine layers."""

from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    """Supported permission modes."""

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"

# questor: allow R7 -- until W8 adds the mirror test
