"""Backwards-compatible re-export of the generic file-lock helpers.

The implementation lives in :mod:`questorharness.contracts.locking`. This module
is retained so existing callers (swarm mailbox, permission sync, external
plugins) keep working without changes.
"""

from __future__ import annotations

from questorharness.contracts.locking import (
    SwarmLockError,
    SwarmLockUnavailableError,
    _exclusive_posix_lock,
    _exclusive_windows_lock,
    exclusive_file_lock,
)

__all__ = [
    "SwarmLockError",
    "SwarmLockUnavailableError",
    "_exclusive_posix_lock",
    "_exclusive_windows_lock",
    "exclusive_file_lock",
]
