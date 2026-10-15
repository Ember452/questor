"""Shared, UI-independent primitives for the L0 vocabulary (design/01).

Adapted in shape from DeepCode ``core/domain/common.py``; kept dependency-light
(stdlib only). These are the invariant helpers contracts and state build on.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

JsonObject = Mapping[str, Any]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp (never naive)."""
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Opaque, type-prefixed id (e.g. ``run_ab12...``); validated for safety."""
    if not prefix or not prefix.isascii() or not prefix.replace("_", "").isalnum():
        raise ValueError("identifier prefix must be non-empty ASCII alphanumeric")
    return f"{prefix}_{uuid.uuid4().hex}"


def require_prefixed_id(value: str, prefix: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith(f"{prefix}_")
        or len(value) <= len(prefix) + 1
    ):
        raise ValueError(f"expected a {prefix}_ identifier")


def require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def require_non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def validate_json_object(value: Any, name: str) -> None:
    """Reject values that are not JSON-safe (blocks NaN/Inf and non-mappings)."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    try:
        json.dumps(dict(value), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON-safe values") from exc


def enum_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)
