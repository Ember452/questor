"""Stop task helper."""

from __future__ import annotations

from questorharness.runtime.tasks.task_manager import get_task_manager
from questorharness.contracts.task import TaskRecord


async def stop_task(task_id: str) -> TaskRecord:
    """Stop a running task via the default task manager."""
    return await get_task_manager().stop_task(task_id)

# questor: allow R7 -- until W8 adds the mirror test
