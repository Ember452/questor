"""Compatibility surface for coordinator mode.

Implementation lives in ``team_registry`` (state), ``notifications``
(envelopes) and ``capabilities.context.coordinator`` (mode and prompt).
"""

from __future__ import annotations

from questorharness.capabilities.context.coordinator import (
    get_coordinator_system_prompt,
    get_coordinator_tools,
    get_coordinator_user_context,
    is_coordinator_mode,
    match_session_mode,
)
from questorharness.runtime.coordinator.notifications import (
    TaskNotification,
    WorkerConfig,
    format_task_notification,
    parse_task_notification,
)
from questorharness.runtime.coordinator.team_registry import (
    TeamRecord,
    TeamRegistry,
    get_team_registry,
)

__all__ = [
    "TaskNotification",
    "TeamRecord",
    "TeamRegistry",
    "WorkerConfig",
    "format_task_notification",
    "get_coordinator_system_prompt",
    "get_coordinator_tools",
    "get_coordinator_user_context",
    "get_team_registry",
    "is_coordinator_mode",
    "match_session_mode",
    "parse_task_notification",
]
